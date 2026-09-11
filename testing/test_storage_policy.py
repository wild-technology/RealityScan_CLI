"""Offline capacity/cleanup policy tests; no data or installation mutation."""
from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules import storage_policy as sp


@pytest.fixture
def volume_probe(monkeypatch):
    locations, free, calls = {}, {}, []

    def resolve(path):
        key = locations[str(path)]
        return {'volume_id': key, 'anchor': key, 'path': str(path)}

    def usage(anchor):
        calls.append(anchor)
        value = free[anchor]
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(free=round(value * sp.GIB))

    monkeypatch.setattr(sp, 'resolve_volume', resolve)
    monkeypatch.setattr(sp.shutil, 'disk_usage', usage)
    return locations, free, calls


def test_shared_volume_sums_both_deltas_reserves_once_and_samples_once(volume_probe):
    locations, free, calls = volume_probe
    locations.update({'F:/NA171/proc': 'volume-F', 'F:/NA171/proc/tmp/cache': 'volume-F'})
    free['volume-F'] = 140  # Synthetic sample, not a live measurement of F:.
    demands = [sp.StorageDemand('F:/NA171/proc', 23.8, 'output'),
               sp.StorageDemand('F:/NA171/proc/tmp/cache', 72, 'cache')]
    report = sp.assess_storage(demands)
    assert not report['can_start']
    assert len(report['volumes']) == 1
    volume = report['volumes'][0]
    assert volume['required_bytes'] == sp._bytes(23.8, 'test') + 122 * sp.GIB
    assert volume['reserve_bytes'] == 50 * sp.GIB
    assert calls == ['volume-F']
    assert 'output + cache' in report['alerts'][0]['message']


def test_distinct_volumes_each_get_a_reserve(volume_probe):
    locations, free, calls = volume_probe
    locations.update({'results': 'vol1', 'cache': 'vol2'})
    free.update(vol1=80, vol2=125)
    report = sp.assess_storage([sp.StorageDemand('results', 20, 'output'),
                                sp.StorageDemand('cache', 72, 'cache')])
    assert report['can_start']
    assert sorted(v['required_bytes'] // sp.GIB for v in report['volumes']) == [70, 122]
    assert sorted(calls) == ['vol1', 'vol2']


def test_mounts_on_same_drive_letter_can_be_distinct_volumes(volume_probe):
    locations, free, _ = volume_probe
    locations.update({'C:/output': 'vol1', 'C:/mounted/cache': 'vol2'})
    free.update(vol1=100, vol2=60)
    report = sp.assess_storage([sp.StorageDemand('C:/output', 10, 'output'),
                                sp.StorageDemand('C:/mounted/cache', 72, 'cache')])
    assert not report['can_start']
    assert len(report['volumes']) == 2


def test_different_drive_aliases_for_same_volume_share_budget(volume_probe):
    locations, free, calls = volume_probe
    locations.update({'F:/output': 'same', 'Z:/alias/cache': 'same'})
    free['same'] = 125
    report = sp.assess_storage([sp.StorageDemand('F:/output', 10, 'output'),
                                sp.StorageDemand('Z:/alias/cache', 72, 'cache')])
    assert not report['can_start']
    assert calls == ['same']


@pytest.mark.parametrize('free_gib,can_start,status', [(59, False, 'block'), (60, True, 'warning'),
                                                    (69, True, 'warning'), (70, True, 'ok')])
def test_capacity_boundary_and_runtime_alerts(volume_probe, free_gib, can_start, status):
    locations, free, _ = volume_probe
    locations['output'] = 'vol'
    free['vol'] = free_gib
    report = sp.assess_storage([sp.StorageDemand('output', 10, 'output')])
    assert report['can_start'] is can_start
    assert report['volumes'][0]['status'] == status
    assert not report['automatic_deletion']


@pytest.mark.parametrize('value', [-1, float('nan'), float('inf'), True, None, '10', 1e308, 10**400])
def test_invalid_delta_refused_before_any_probe(volume_probe, value):
    _, _, calls = volume_probe
    with pytest.raises(sp.StoragePolicyError):
        sp.assess_storage([sp.StorageDemand('output', value, 'output')])
    assert calls == []


def test_unknown_volume_and_unreadable_free_space_block(volume_probe, monkeypatch):
    def unavailable(path):
        raise OSError('drive disconnected')
    monkeypatch.setattr(sp, 'resolve_volume', unavailable)
    report = sp.assess_storage([sp.StorageDemand('output', 1, 'output')])
    assert not report['can_start'] and 'drive disconnected' in report['alerts'][0]['message']


def test_free_space_error_is_not_treated_as_zero_or_skipped(volume_probe):
    locations, free, _ = volume_probe
    locations['output'] = 'vol'
    free['vol'] = PermissionError('quota unavailable')
    report = sp.assess_storage([sp.StorageDemand('output', 0, 'output')])
    assert not report['can_start']
    assert report['volumes'][0]['free_bytes'] is None


def test_start_gate_resamples_and_raises_without_deleting(volume_probe):
    locations, free, calls = volume_probe
    locations['output'] = 'vol'
    free['vol'] = 100
    demands = [sp.StorageDemand('output', 10, 'output')]
    assert sp.assess_storage(demands)['can_start']
    free['vol'] = 55
    with pytest.raises(sp.StorageBlocked) as error:
        sp.require_start_space(demands)
    assert not error.value.report['can_start']
    assert calls == ['vol', 'vol']


def test_runtime_remaining_growth_not_original_allocation(volume_probe):
    locations, free, _ = volume_probe
    locations['output'] = 'vol'
    free['vol'] = 54
    report = sp.assess_storage([sp.StorageDemand('output', 0, 'remaining')])
    assert report['can_start']
    assert report['alerts'][0]['level'] == 'warning'


def test_below_reserve_blocks_even_without_additional_growth(volume_probe):
    locations, free, _ = volume_probe
    locations['output'] = 'vol'
    free['vol'] = 49
    report = sp.assess_storage([sp.StorageDemand('output', 0, 'remaining')])
    assert not report['can_start'] and report['volumes'][0]['status'] == 'block'


def test_duplicate_demand_labels_and_empty_demand_list_rejected(volume_probe):
    locations, free, _ = volume_probe
    locations['path'] = 'vol'
    free['vol'] = 100
    with pytest.raises(sp.StoragePolicyError, match='unique'):
        sp.assess_storage([sp.StorageDemand('path', 1, 'output')] * 2)
    with pytest.raises(sp.StoragePolicyError, match='At least one'):
        sp.assess_storage([])


def test_native_volume_resolution_of_missing_destinations_is_read_only(tmp_path):
    # Uses a temp path on the host filesystem, not any project/data/install path.
    report = sp.resolve_volume(tmp_path / 'not-created' / 'cache')
    assert report['volume_id']
    assert Path(report['anchor']) == tmp_path
    assert not (tmp_path / 'not-created').exists()
    with pytest.raises(sp.StoragePolicyError, match='Absolute'):
        sp.resolve_volume('relative/output')


@pytest.fixture
def cleanup(tmp_path):
    root = tmp_path / 'project'
    path = root / 'proc' / 'tmp' / 'stage' / 'scratch.bin'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'owned temporary data')
    item = {'path': 'proc/tmp/stage/scratch.bin', 'kind': 'temporary',
            'owner_id': 'worker-1', 'producer_stage': 'model', 'attempt_id': 'attempt-1',
            'size_bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest = {'schema': 1, 'project_id': 'project-1', 'files': [item]}
    evidence = {'model': {'attempt_id': 'attempt-1', 'saved': True, 'verified': True}}

    def plan(**kwargs):
        return sp.plan_cleanup(root, manifest, project_id='project-1', stage_evidence=evidence,
                               active_owner_ids=kwargs.pop('active_owner_ids', set()), **kwargs)

    return root, path, item, manifest, evidence, plan


def test_cleanup_is_exact_read_only_manifest_plan(cleanup):
    root, path, item, _, _, plan = cleanup
    unmanaged = path.parent / 'unmanaged.bin'
    unmanaged.write_bytes(b'not in manifest')
    before = path.read_bytes()
    report = plan()
    assert len(report['candidates']) == 1
    assert report['candidates'][0]['absolute_path'] == str(path)
    assert report['reclaimable_bytes'] == item['size_bytes']
    assert report['refused'] == []
    assert report['requires_explicit_review'] and not report['automatic_deletion']
    assert path.read_bytes() == before and unmanaged.read_bytes() == b'not in manifest'


@pytest.mark.parametrize('active', [None, {'worker-1'}, {'other-consumer'}])
def test_unknown_or_any_active_owner_blocks_all_cleanup(cleanup, active):
    _, path, _, _, _, plan = cleanup
    report = plan(active_owner_ids=active)
    assert not report['candidates'] and report['reclaimable_bytes'] == 0
    assert path.exists()


@pytest.mark.parametrize('field,value', [('saved', False), ('saved', 1), ('saved', 'true'),
                                       ('verified', False), ('verified', 1), ('attempt_id', 'old'),
                                       ('active', True)])
def test_checkpoint_must_be_explicit_saved_verified_same_attempt(cleanup, field, value):
    _, path, _, _, evidence, plan = cleanup
    evidence['model'][field] = value
    assert not plan()['candidates']
    assert path.exists()


@pytest.mark.parametrize('path', ['raw/photo.jpg', 'source/photo.jpg', 'proc/model.obj',
                                 'proc/tmp/exports/model.obj', 'proc/tmp/raw/photo.jpg',
                                 'proc/tmp/../model.obj', 'proc/tmp/a:stream',
                                 'proc/tmp/file.', 'proc/tmp/NUL', 'proc\\tmp\\file',
                                 'F:/NA171/proc/tmp/file', 'proc/tmp//file'])
def test_unsafe_source_raw_deliverable_and_alias_paths_refused(cleanup, path):
    _, _, item, _, _, plan = cleanup
    item['path'] = path
    assert not plan()['candidates']


@pytest.mark.parametrize('field,value', [('kind', 'deliverable'), ('owner_id', ''),
                                       ('attempt_id', ''), ('producer_stage', 'unknown'),
                                       ('size_bytes', -1), ('size_bytes', True), ('sha256', 'wrong')])
def test_unowned_or_unfingerprinted_entries_are_refused(cleanup, field, value):
    _, _, item, _, _, plan = cleanup
    item[field] = value
    assert not plan()['candidates']


def test_changed_file_and_missing_file_are_refused(cleanup):
    _, path, _, _, _, plan = cleanup
    path.write_bytes(b'new content')
    assert not plan()['candidates']
    path.unlink()
    assert not plan()['candidates']


def test_protected_path_and_directory_are_never_targets(cleanup):
    root, path, item, _, _, plan = cleanup
    assert not plan(protected_paths=[path.parent])['candidates']
    item['path'] = 'proc/tmp/stage'
    assert not plan()['candidates']
    assert path.exists()


def test_hardlink_to_source_is_refused(cleanup):
    root, path, _, _, _, plan = cleanup
    source = root.parent / 'source.bin'
    os.link(path, source)
    assert not plan()['candidates']
    assert source.exists() and path.exists()


def test_junction_path_is_refused(cleanup, monkeypatch):
    _, path, _, _, _, plan = cleanup
    monkeypatch.setattr(Path, 'is_junction', lambda p: p == path.parent)
    assert not plan()['candidates']


def test_duplicate_manifest_paths_do_not_create_partial_unsafe_plan(cleanup):
    _, _, item, manifest, _, plan = cleanup
    second = copy.deepcopy(item)
    second['path'] = second['path'].upper()
    manifest['files'].append(second)
    with pytest.raises(sp.StoragePolicyError, match='Duplicate'):
        plan()


def test_mismatched_project_id_rejects_manifest(cleanup):
    _, _, _, manifest, _, plan = cleanup
    manifest['project_id'] = 'different-project'
    with pytest.raises(sp.StoragePolicyError, match='ownership'):
        plan()


def test_path_becomes_redirected_during_hashing_is_refused(cleanup, monkeypatch):
    _, path, _, _, _, plan = cleanup
    real_digest = hashlib.file_digest
    redirected = False

    def changed(stream, digest):
        nonlocal redirected
        result = real_digest(stream, digest)
        redirected = True
        return result

    monkeypatch.setattr(sp.hashlib, 'file_digest', changed)
    monkeypatch.setattr(Path, 'is_junction', lambda p: redirected and p == path.parent)
    report = plan()
    assert not report['candidates'] and 'Redirected' in report['refused'][0]['reason']


@pytest.mark.parametrize('cache_volume,free_results,free_cache,blocks', [
    ('same', 125, 125, True), ('same', 132, 132, False),
    ('separate', 65, 121, True), ('separate', 65, 122, False)])
def test_preflight_models_charge_cache_on_shared_and_distinct_volumes(
        tmp_path, volume_probe, monkeypatch, cache_volume, free_results, free_cache, blocks):
    from modules.preflight import Preflight
    from modules.run_charter import RunCharter
    from modules.realityscan_interface.realityscan_cli import RealityScanCLI

    monkeypatch.setattr(RealityScanCLI, 'find_executable', lambda self: 'fixture.exe')
    locations, free, calls = volume_probe
    results, cache = str(tmp_path / 'results'), str(tmp_path / 'cache')
    locations.update({results: 'same', cache: cache_volume})
    free.update({'same': free_results, cache_volume: free_cache})
    charter = RunCharter(results_root=results, rs_cache_dir=cache,
                         budget={'disk_delta_gb': 10})
    oracle = Preflight(charter, stages=['model'])
    oracle.check_machine()
    assert bool(oracle.blocking) is blocks
    assert len(calls) == (1 if cache_volume == 'same' else 2)
    if blocks:
        assert any('reserve' in row for row in oracle.blocking)
