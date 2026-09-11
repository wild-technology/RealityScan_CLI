"""Deployment regressions: pure attribution and mocked workflows, never RS."""
import csv
import json
import logging
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

import merge_zones as merge


LOG = logging.getLogger(__name__)


def component(name, images, root=None):
    path = (root or Path('fixture')) / f'{name}.rsalign'
    if root is not None:
        path.write_bytes(name.encode())
    return dict(schema=1, zone='zone', component=name, rsalign=str(path),
                images=images, camera_count=len(images), bbox_utm=[0, 0, 10, 10])


def overlap_pair():
    shared = [f's{i}.jpg' for i in range(80)]
    return [component('a', shared + [f'a{i}.jpg' for i in range(20)]),
            component('b', shared + [f'b{i}.jpg' for i in range(20)])]


def test_count_only_never_certifies_membership_or_retention():
    comps = overlap_pair()
    results, confidence = merge.attribute_result(comps, [180, 100, 100], LOG)
    result = results[0]
    assert confidence == 'count_only'
    assert result['members'] is result['loss'] is result['collapsed'] is None
    assert not merge.acceptance_verdict(True, 1, True, confidence, None, 0)[0]


@pytest.mark.parametrize('tolerance,accepted', [(0, False), (19, False), (20, True)])
def test_measured_duplicate_copies_do_not_hide_unique_loss(tolerance, accepted):
    comps = overlap_pair()
    observed = comps[0]['images'] + comps[1]['images'][:80]
    results, confidence = merge.attribute_result(
        comps, [180, 100, 100], LOG, loss_tolerance=tolerance,
        peel_members=[observed] + [c['images'] for c in comps])
    if accepted:
        assert confidence == 'exact'
        assert results[0]['loss'] == 20
        assert results[0]['collapsed'] == 0
        assert len(results[0]['members']) == 180
        assert not set(comps[1]['images'][80:]) & set(results[0]['members'])
    else:
        assert confidence == 'ambiguous'
        assert not results[0]['inputs']


@pytest.mark.parametrize('extra_copies', [0, 30, 80])
def test_measured_folded_partial_and_additive_fusions(extra_copies):
    comps = overlap_pair()
    unique = list(dict.fromkeys(comps[0]['images'] + comps[1]['images']))
    observed = unique + comps[0]['images'][:extra_copies]
    results, confidence = merge.attribute_result(
        comps, [len(observed), 100, 100], LOG,
        peel_members=[observed] + [c['images'] for c in comps])
    assert confidence == 'exact'
    assert results[0]['members'] == observed
    assert results[0]['loss'] == 0
    assert results[0]['collapsed'] == 80 - extra_copies
    assert merge.acceptance_verdict(True, 1, True, confidence, 0, 0)[0]


def test_measured_membership_disambiguates_equal_counts():
    comps = [component(n, [f'{n}{i}.jpg' for i in range(2)]) for n in 'abc']
    observed = [comps[0]['images'] + comps[2]['images'], comps[1]['images']]
    results, confidence = merge.attribute_result(comps, [4, 2], LOG, peel_members=observed)
    assert confidence == 'exact'
    assert results[0]['inputs'] == ['zone/a', 'zone/c']


def test_unexpected_camera_is_not_attributed():
    comps = [component('a', ['a.jpg']), component('b', ['b.jpg'])]
    _, confidence = merge.attribute_result(comps, [2], LOG,
                                            peel_members=[['a.jpg', 'unknown.jpg']])
    assert confidence == 'ambiguous'


def test_full_union_search_is_linear_even_for_fragmented_zones():
    comps = [component(str(i), [f'{i}.jpg']) for i in range(50)]
    calls = []
    def profile(frame, event, arg):
        if event == 'call' and frame.f_code.co_name == 'search':
            calls.append(1)
    previous = sys.getprofile()
    try:
        sys.setprofile(profile)
        results, confidence = merge.attribute_result(
            comps, [50], LOG, peel_members=[[f'{i}.jpg' for i in range(50)]])
    finally:
        sys.setprofile(previous)
    assert confidence == 'exact' and len(results[0]['inputs']) == 50
    assert len(calls) <= 101


def test_combinatorial_ambiguity_is_bounded_and_refused():
    comps = [component(str(i), [f'{i}.jpg']) for i in range(25)]
    _, confidence = merge.attribute_result(comps, [12], LOG)
    assert confidence == 'ambiguous'


def write_csv(path, names, count=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as fh:
        fh.write(f'#cameras {len(names) if count is None else count}\n')
        csv.writer(fh).writerows([[name, '0', '0'] for name in names])


def test_registration_reader_preserves_quoted_paths_and_duplicates(tmp_path):
    names = ['C:/images/a,b.jpg', 'C:/images/a,b.jpg']
    write_csv(tmp_path / 'identity' / 'fused_c0.csv', names)
    assert merge.peel_members_from(str(tmp_path), 'fused', [2]) == [names]


@pytest.mark.parametrize('names,header,expected', [(['a'], 2, 1),
                                                (['a'], 2, 2), ([''], 1, 1)])
def test_registration_reader_refuses_broken_measurement(tmp_path, names, header, expected):
    write_csv(tmp_path / 'identity' / 'fused_c0.csv', names, header)
    with pytest.raises(ValueError):
        merge.peel_members_from(str(tmp_path), 'fused', [expected])


def stub_cluster(monkeypatch, tmp_path, success=True, fuse=False, members=True):
    comps = [component('a', ['a0', 'a1', 'a2'], tmp_path),
             component('b', ['b0', 'b1'], tmp_path)]
    calls = []
    monkeypatch.delenv('RS_ALIGN_POOL_DIR', raising=False)
    monkeypatch.setattr(merge, 'build_union_flight_log', lambda *a, **k: ('nav', 'params'))
    monkeypatch.setattr(merge, 'snapshot_rs_log', lambda *a: None)
    monkeypatch.setattr(merge, 'rs_finalizing_counts', lambda *a: {})
    monkeypatch.setattr(merge.camera_registry, 'sanitize_and_census', lambda *a: (0, 0, 0))
    monkeypatch.setattr(merge.component_manifest, 'bbox_from_flight_log', lambda *a: [0, 0, 10, 10])
    def workflow(cli, complist, out, name, *args, **kwargs):
        calls.append(Path(out))
        if success:
            groups = [c['images'] for c in comps]
            if fuse:
                groups.insert(0, comps[0]['images'] + comps[1]['images'])
            for i, names in enumerate(groups):
                (Path(out) / f'{name}_c{i}.rsalign').write_bytes(b'mocked component')
                directory = Path(out) / f'identity_r{i}'
                directory.mkdir()
                for j in range(len(names)):
                    (directory / f'{j}.xmp').write_text('mocked pose')
                if members:
                    write_csv(Path(out) / 'identity' / f'{name}_c{i}.csv', names)
        return SimpleNamespace(success=success, errors=[] if success else ['mock failure'])
    monkeypatch.setattr(merge, 'run_merge_workflow', workflow)
    def run(ceiling=100):
        return merge.merge_cluster(None, comps, 0, str(tmp_path), 'images',
                                   merge.LADDERS['merge_first'], 1, 'logs', LOG,
                                   max_scene_cameras=ceiling)
    return run, calls


def test_failed_ladder_is_not_converged(tmp_path, monkeypatch):
    run, calls = stub_cluster(monkeypatch, tmp_path, success=False)
    result = run()
    assert len(calls) == 2 and not result['converged']
    assert result['unresolved_subsets']


def test_ceiling_refusal_is_not_converged(tmp_path, monkeypatch):
    run, calls = stub_cluster(monkeypatch, tmp_path)
    assert not run(ceiling=4)['converged']
    assert not calls


def test_clean_nonfusion_is_converged(tmp_path, monkeypatch):
    run, calls = stub_cluster(monkeypatch, tmp_path)
    assert run()['converged']
    assert len(calls) == 2  # symmetric subsets are not repeated


def test_measured_fusion_is_adopted_and_manifested(tmp_path, monkeypatch):
    run, calls = stub_cluster(monkeypatch, tmp_path, fuse=True)
    result = run()
    assert result['converged'] and len(calls) == 1
    assert result['attempts'][0]['accepted']
    final = result['final_components'][0]
    manifest = json.loads(Path(final['rsalign'] + '.manifest.json').read_text())
    assert manifest['images'] == ['a0', 'a1', 'a2', 'b0', 'b1']


def test_count_only_fusion_cannot_write_a_manifest(tmp_path, monkeypatch):
    run, calls = stub_cluster(monkeypatch, tmp_path, fuse=True, members=False)
    result = run()
    assert not result['converged']
    assert not list(tmp_path.rglob('*.manifest.json'))
    assert not any(a.get('accepted') for a in result['attempts'])


def test_retry_uses_fresh_directories_and_leaves_old_markers(tmp_path, monkeypatch):
    run, calls = stub_cluster(monkeypatch, tmp_path)
    assert run()['converged']
    old = calls[0]
    (old / 'PEEL_TRUNCATED.txt').write_text('old failure')
    (old / 'identity_r0' / 'stale.xmp').write_text('old pose')
    calls.clear()
    assert run()['converged']
    assert all(p.parent != old.parent for p in calls)
    assert (old / 'PEEL_TRUNCATED.txt').read_text() == 'old failure'


def fingerprint(comps, **kwargs):
    return merge.run_fingerprint([merge.component_analysis.component_key(c) for c in comps],
                                 'merge_first', 'neighbour', 'overlap', 0, 1, False,
                                 input_manifests=comps, **kwargs)


def resume_report(tmp_path, comps, converged=True):
    fp = fingerprint(comps)
    record = dict(inputs=[merge.component_analysis.component_key(c) for c in comps],
                  cluster='cluster_0', converged=converged, final_components=comps,
                  final_identities=[merge.component_identity(c) for c in comps])
    (tmp_path / 'merge_report.json').write_text(json.dumps(
        dict(run_fingerprint=fp, clusters=[record])))
    return fp


def test_resume_requires_input_and_output_content(tmp_path):
    comps = [component('a', ['a.jpg'], tmp_path)]
    fp = resume_report(tmp_path, comps)
    assert merge.load_resumable_clusters(str(tmp_path), fp, LOG)
    Path(comps[0]['rsalign']).write_bytes(b'z')  # same name and size
    assert fingerprint(comps) != fp
    assert not merge.load_resumable_clusters(str(tmp_path), fp, LOG)


def test_failed_cluster_is_not_resumed(tmp_path):
    comps = [component('a', ['a.jpg'], tmp_path)]
    fp = resume_report(tmp_path, comps, converged=False)
    assert not merge.load_resumable_clusters(str(tmp_path), fp, LOG)


def test_legacy_name_only_fingerprint_is_not_resumable(tmp_path):
    comps = [component('a', ['a.jpg'], tmp_path)]
    resume_report(tmp_path, comps)
    fp = merge.run_fingerprint(['zone/a'], 'merge_first', 'neighbour', 'overlap', 0, 1, False)
    assert not merge.load_resumable_clusters(str(tmp_path), fp, LOG)


def test_fingerprint_tracks_membership_provenance_and_ceiling(tmp_path):
    comps = [component('a', ['a.jpg'], tmp_path)]
    original = fingerprint(comps)
    assert fingerprint(comps, max_scene_cameras=1) != original
    assert fingerprint([dict(comps[0], images=['b.jpg'])]) != original
    (tmp_path / 'align_inputs.json').write_text('{"frame":"local"}')
    assert fingerprint(comps) != original


def test_fingerprint_tracks_current_navigation(tmp_path):
    comps = [component('a', ['a.jpg'], tmp_path)]
    nav = tmp_path / 'flight_log_18N_UTM.txt'
    nav.write_text('old')
    original = fingerprint(comps, images_root=str(tmp_path))
    nav.write_text('new')
    assert fingerprint(comps, images_root=str(tmp_path)) != original


def test_changed_registration_invalidates_resumed_output(tmp_path):
    comps = [component('a', ['a.jpg'], tmp_path)]
    path = tmp_path / 'identity' / 'a.csv'
    write_csv(path, ['a.jpg'])
    fp = resume_report(tmp_path, comps)
    write_csv(path, ['b.jpg'])
    assert not merge.load_resumable_clusters(str(tmp_path), fp, LOG)


def test_invalid_report_shape_is_not_resumed(tmp_path):
    comps = [component('a', ['a.jpg'], tmp_path)]
    (tmp_path / 'merge_report.json').write_text('[]')
    assert not merge.load_resumable_clusters(str(tmp_path), fingerprint(comps), LOG)


def test_pool_marker_refused_even_without_environment_override(tmp_path, monkeypatch):
    monkeypatch.delenv('RS_ALIGN_POOL_DIR', raising=False)
    (tmp_path / 'batch_inputs.json').write_text(json.dumps(
        {'params': {'batch_zone_layout': 'pool'}}))
    with pytest.raises(ValueError, match='source-backed'):
        merge.assert_safe_merge_harvest(str(tmp_path))


def test_incomplete_main_does_not_launch_assembly_or_preserve_success(tmp_path, monkeypatch):
    comps = [component('a', ['a.jpg'], tmp_path)]
    output = tmp_path / 'merged'
    output.mkdir()
    (output / 'EVALUATION_READY.txt').write_text('previous successful run')
    class Settings:
        def ask(self, section, key, value, fallback):
            return value if value is not None else fallback
    monkeypatch.delenv('RS_ALIGN_POOL_DIR', raising=False)
    monkeypatch.setattr(merge, 'SettingsStore', Settings)
    monkeypatch.setattr(merge, 'realityscan_env', lambda s: {'RS_HEADLESS': '1'})
    monkeypatch.setattr(merge, 'assert_harvestable', lambda *a: None)
    monkeypatch.setattr(merge, 'load_inputs', lambda *a: comps)
    monkeypatch.setattr(merge, 'build_union_flight_log', lambda *a, **k: ('nav', 'params'))
    monkeypatch.setattr(merge, 'measure_input_scales', lambda *a, **k: {})
    monkeypatch.setattr(merge, 'RealityScanCLI', lambda *a: None)
    monkeypatch.setattr(merge, 'merge_cluster', lambda *a, **k: dict(
        cluster='cluster_0', inputs=['zone/a'], converged=False, final_components=comps))
    def forbidden(*args, **kwargs):
        pytest.fail('assembly must not launch after an incomplete merge')
    monkeypatch.setattr(merge, 'run_merge_workflow', forbidden)
    monkeypatch.setattr(sys, 'argv', ['merge_zones.py', '--components_root', str(tmp_path),
                                     '--images_root', str(tmp_path), '--output', str(output),
                                     '--resume', 'false'])
    assert merge.main() == 1
    report = json.loads((output / 'merge_report.json').read_text())
    assert report['assembly']['workflow_success'] is False
    assert report['evaluation_blocked']
    assert not (output / 'assembly').exists()


def test_pool_refusal_precedes_settings_and_output_creation(tmp_path, monkeypatch):
    monkeypatch.setenv('RS_ALIGN_POOL_DIR', str(tmp_path / 'source'))
    def forbidden(*args, **kwargs):
        pytest.fail('write-capable operation reached before pool refusal')
    monkeypatch.setattr(merge, 'SettingsStore', forbidden)
    assert merge.main() == 1
    monkeypatch.setattr(merge.tempfile, 'mkdtemp', forbidden)
    with pytest.raises(ValueError, match='source-backed'):
        merge.merge_cluster(None, [], 0, str(tmp_path), 'images', [], 1, 'logs', LOG)
    with pytest.raises(ValueError, match='source-backed'):
        merge.run_merge_workflow(None, '', '', '', '', [], None, None, '', '', True, LOG)


def test_batch_refuses_pool_before_setup_and_reused_attempts_before_launch():
    path = Path(merge.__file__).parent / 'modules/realityscan_interface/RS_CLI/Scripts/MergeZoneComponents.bat'
    raw = path.read_bytes()
    assert b'\n' not in raw.replace(b'\r\n', b'')
    source = raw.decode()
    assert source.index('if defined RS_ALIGN_POOL_DIR goto :sourcePoolRefused') < source.index('call "%~dp0SetVariables.bat"')
    assert source.index('do goto :dirtyOutput') < source.index('call "%~dp0startRealityScan.bat"')
    assert source.index('-exportRegistration "%registration_csv%"') < source.index('call :run -deleteSelectedComponent')


def test_abort_guard_immediately_precedes_every_mutating_dispatch_and_boot():
    path = Path(merge.__file__).parent / 'modules/realityscan_interface/RS_CLI/Scripts/MergeZoneComponents.bat'
    lines = [line.strip() for line in path.read_text().splitlines()]
    guard = 'call "%~dp0RuntimeAbortGuard.bat" || exit /b 1223'
    dispatches = []
    for index, line in enumerate(lines):
        if (line.lower().startswith('%realityscan% -delegateto ')
                or line.lower() == 'call "%~dp0startrealityscan.bat"'):
            assert lines[index - 1] == guard, f'unguarded dispatch at line {index + 1}: {line}'
            dispatches.append(index)
        if line.lower().startswith('%realityscan% ') and any(
                command in line.lower() for command in ('-getstatus', '-waitcompleted')):
            assert lines[index - 1] != guard, 'read/wait dispatch should remain unguarded'
        if line == guard:
            following = lines[index + 1].lower()
            assert (following.startswith('%realityscan% -delegateto ')
                    or following == 'call "%~dp0startrealityscan.bat"')
    # Covers boot, both direct settings loops, both quits and all three run
    # variants. Guarding only :run leaves the other entry points dispatchable.
    assert len(dispatches) >= 8
    assert sum(lines[i].endswith('-quit') for i in dispatches) == 2
    assert sum(lines[i].endswith('%*') for i in dispatches) == 3
