"""Pure temporary-filesystem checkpoint safety; never starts RealityScan."""
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil

import pytest

from module_base import scene_checkpoint as cp


LOG = logging.getLogger(__name__)


@pytest.fixture
def bundle(tmp_path):
    live = tmp_path / 'live'
    live.mkdir()
    project = live / 'scene.rsproj'
    project.write_bytes(b'GOOD PROJECT')
    data = live / 'scene'
    (data / 'empty').mkdir(parents=True)
    (data / 'state.dat').write_bytes(b'GOOD DATA')
    checkpoints = tmp_path / 'checkpoints'
    return project, data, checkpoints


def snapshot(bundle):
    project, _, checkpoints = bundle
    return Path(cp.checkpoint_scene(str(project), str(checkpoints), 'initial', LOG))


def restore(bundle):
    project, _, checkpoints = bundle
    cp.restore_scene(str(project), str(checkpoints), 'initial', LOG)


def changed_live(bundle):
    project, data, _ = bundle
    project.write_bytes(b'CURRENT PROJECT')
    (data / 'state.dat').write_bytes(b'CURRENT DATA')


def assert_current(bundle):
    project, data, _ = bundle
    assert project.read_bytes() == b'CURRENT PROJECT'
    assert (data / 'state.dat').read_bytes() == b'CURRENT DATA'


def write_manifest(checkpoint, change):
    path = checkpoint / cp.MANIFEST
    manifest = json.loads(path.read_text(encoding='utf-8'))
    change(manifest)
    path.write_text(json.dumps(manifest), encoding='utf-8')


def test_manifest_hashes_files_and_records_empty_directories(bundle):
    checkpoint = snapshot(bundle)
    manifest = json.loads((checkpoint / cp.MANIFEST).read_text(encoding='utf-8'))
    assert manifest['source_scene'] == os.path.normcase(str(bundle[0]))
    assert manifest['entries']['scene.rsproj'] == {
        'kind': 'file', 'size': 12, 'sha256': hashlib.sha256(b'GOOD PROJECT').hexdigest()}
    assert manifest['entries']['scene/empty'] == {'kind': 'directory'}


@pytest.mark.parametrize('missing', [True, False])
def test_missing_or_empty_source_cannot_replace_good_checkpoint(bundle, missing):
    checkpoint = snapshot(bundle)
    original = (checkpoint / cp.MANIFEST).read_bytes()
    if missing:
        bundle[0].unlink()
    else:
        bundle[0].write_bytes(b'')
    with pytest.raises(ValueError, match='missing/empty'):
        snapshot(bundle)
    assert (checkpoint / cp.MANIFEST).read_bytes() == original
    assert (checkpoint / 'scene.rsproj').read_bytes() == b'GOOD PROJECT'


@pytest.mark.parametrize('tag', ['', '..', '../other', r'..\other', '/tmp/other',
                                 r'C:\other', 'C:other', 'name:stream', 'name.', 'name ',
                                 'CON', 'nul.data', '.checkpoint-hidden'])
def test_unsafe_tag_refused_before_writes(bundle, tag):
    project, _, checkpoints = bundle
    with pytest.raises(ValueError, match='Unsafe checkpoint tag'):
        cp.checkpoint_scene(str(project), str(checkpoints), tag, LOG)
    assert not checkpoints.exists()
    assert project.read_bytes() == b'GOOD PROJECT'


@pytest.mark.parametrize('location', ['companion', 'ancestor', 'project'])
def test_overlapping_checkpoint_root_refused(bundle, location):
    project, data, _ = bundle
    root = {'companion': data / 'checkpoints', 'ancestor': project.parent, 'project': project}[location]
    with pytest.raises(ValueError, match='overlaps'):
        cp.checkpoint_scene(str(project), str(root), 'initial', LOG)
    assert project.read_bytes() == b'GOOD PROJECT'


@pytest.mark.parametrize('damage', ['empty_tag', 'missing_manifest', 'project_hash',
                                    'empty_project', 'extra_file', 'missing_data',
                                    'traversal_name', 'traversal_entry', 'wrong_source',
                                    'duplicate_name', 'version', 'duplicate_key'])
def test_invalid_checkpoint_never_touches_live_bundle(bundle, damage):
    checkpoint = snapshot(bundle)
    changed_live(bundle)
    if damage == 'empty_tag':
        shutil.rmtree(checkpoint)
        checkpoint.mkdir()
    elif damage == 'missing_manifest':
        (checkpoint / cp.MANIFEST).unlink()
    elif damage == 'project_hash':
        (checkpoint / 'scene.rsproj').write_bytes(b'EVIL PROJECT')
    elif damage == 'empty_project':
        (checkpoint / 'scene.rsproj').write_bytes(b'')
    elif damage == 'extra_file':
        (checkpoint / 'other.txt').write_bytes(b'extra')
    elif damage == 'missing_data':
        (checkpoint / 'scene' / 'state.dat').unlink()
    elif damage == 'traversal_name':
        write_manifest(checkpoint, lambda m: m['bundle_names'].append('../outside'))
    elif damage == 'traversal_entry':
        write_manifest(checkpoint, lambda m: m['entries'].update({'../outside': {'kind': 'directory'}}))
    elif damage == 'wrong_source':
        write_manifest(checkpoint, lambda m: m.update(source_scene=str(bundle[0].parent / 'other.rsproj')))
    elif damage == 'duplicate_name':
        write_manifest(checkpoint, lambda m: m['bundle_names'].append('scene.rsproj'))
    elif damage == 'version':
        write_manifest(checkpoint, lambda m: m.update(schema_version=True))
    else:
        path = checkpoint / cp.MANIFEST
        path.write_text(path.read_text(encoding='utf-8').replace('"schema_version": 1',
                        '"schema_version": 1, "schema_version": 1'), encoding='utf-8')
    with pytest.raises(ValueError):
        restore(bundle)
    assert_current(bundle)


@pytest.mark.parametrize('marker', ['scene/.lock', 'scene/sub/writer.LOCK',
                                   'scene.rsproj.lock', 'scene.lock', '.lock'])
def test_restore_refuses_even_closed_lock_markers(bundle, marker):
    snapshot(bundle)
    changed_live(bundle)
    lock = bundle[0].parent / marker
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_bytes(b'lock')
    with pytest.raises(RuntimeError, match='scene lock present'):
        restore(bundle)
    assert lock.read_bytes() == b'lock'
    assert_current(bundle)


def test_new_lock_during_staging_refuses_commit(bundle, monkeypatch):
    snapshot(bundle)
    changed_live(bundle)
    real_copy = cp._copy

    def copy_and_lock(*args, **kwargs):
        real_copy(*args, **kwargs)
        (bundle[1] / '.lock').write_bytes(b'lock')

    monkeypatch.setattr(cp, '_copy', copy_and_lock)
    with pytest.raises(RuntimeError, match='live scene unchanged'):
        restore(bundle)
    assert_current(bundle)


@pytest.mark.parametrize('phase', ['checkpoint', 'restore'])
def test_copy_failure_preserves_live_and_previous_checkpoint(bundle, monkeypatch, phase):
    checkpoint = snapshot(bundle)
    changed_live(bundle)
    original = (checkpoint / cp.MANIFEST).read_bytes()

    def fail(*args, **kwargs):
        raise OSError('injected copy failure')

    monkeypatch.setattr(cp.shutil, 'copytree', fail)
    with pytest.raises((OSError, RuntimeError), match='injected copy failure'):
        snapshot(bundle) if phase == 'checkpoint' else restore(bundle)
    assert_current(bundle)
    assert (checkpoint / cp.MANIFEST).read_bytes() == original


def test_source_changes_during_checkpoint_copy_refused(bundle, monkeypatch):
    checkpoint = snapshot(bundle)
    real_copy = cp._copy

    def copy_and_change(*args, **kwargs):
        real_copy(*args, **kwargs)
        bundle[0].write_bytes(b'CHANGED')

    monkeypatch.setattr(cp, '_copy', copy_and_change)
    with pytest.raises(ValueError, match='Scene changed'):
        snapshot(bundle)
    assert (checkpoint / 'scene.rsproj').read_bytes() == b'GOOD PROJECT'


def test_corrupt_staged_restore_never_touches_live(bundle, monkeypatch):
    snapshot(bundle)
    changed_live(bundle)
    real_copy = cp._copy

    def corrupt(base, target, names, **kwargs):
        real_copy(base, target, names, **kwargs)
        (target / 'scene.rsproj').write_bytes(b'CORRUPTED')

    monkeypatch.setattr(cp, '_copy', corrupt)
    with pytest.raises(RuntimeError, match='Staged restore differs'):
        restore(bundle)
    assert_current(bundle)


@pytest.mark.parametrize('rollback_fails', [False, True])
def test_checkpoint_publish_failure_preserves_previous_snapshot(bundle, monkeypatch, rollback_fails):
    checkpoint = snapshot(bundle)
    changed_live(bundle)
    real_replace = cp.os.replace

    def fail(source, target):
        source, target = Path(source), Path(target)
        if target == checkpoint and (source.name.startswith('.checkpoint-') or rollback_fails):
            raise OSError('injected publish failure')
        return real_replace(source, target)

    monkeypatch.setattr(cp.os, 'replace', fail)
    with pytest.raises((OSError, RuntimeError)):
        snapshot(bundle)
    saved = (list(bundle[2].glob('.checkpoint-recovery-*/initial'))[0]
             if rollback_fails else checkpoint)
    assert (saved / 'scene.rsproj').read_bytes() == b'GOOD PROJECT'
    assert (saved / 'scene' / 'state.dat').read_bytes() == b'GOOD DATA'
    assert_current(bundle)


@pytest.mark.parametrize('rollback_fails', [False, True])
def test_restore_commit_failure_retains_all_original_members(bundle, monkeypatch, rollback_fails):
    snapshot(bundle)
    changed_live(bundle)
    real_replace = cp.os.replace

    def fail(source, target):
        source, target = Path(source), Path(target)
        if source.parent.name.startswith('.scene-restore-') and source.name == 'scene':
            raise OSError('injected install failure')
        if rollback_fails and source.parent.name.startswith('.scene-recovery-'):
            raise OSError('injected rollback failure')
        return real_replace(source, target)

    monkeypatch.setattr(cp.os, 'replace', fail)
    with pytest.raises(RuntimeError, match='ROLLBACK INCOMPLETE') as error:
        restore(bundle)
    if rollback_fails:
        backup = list(bundle[0].parent.glob('.scene-recovery-*'))[0]
        assert str(backup) in str(error.value)
        assert (backup / 'scene.rsproj').read_bytes() == b'CURRENT PROJECT'
        assert (backup / 'scene' / 'state.dat').read_bytes() == b'CURRENT DATA'
    else:
        assert_current(bundle)
        assert not list(bundle[0].parent.glob('.scene-recovery-*'))


def test_failure_while_moving_original_bundle_rolls_back(bundle, monkeypatch):
    snapshot(bundle)
    changed_live(bundle)
    real_replace = cp.os.replace

    def fail(source, target):
        if Path(source) == bundle[1]:
            raise OSError('injected backup move failure')
        return real_replace(source, target)

    monkeypatch.setattr(cp.os, 'replace', fail)
    with pytest.raises(RuntimeError, match='Original live bundle restored'):
        restore(bundle)
    assert_current(bundle)


def test_restore_replaces_whole_bundle_without_stale_members(bundle):
    checkpoint = snapshot(bundle)
    changed_live(bundle)
    extra = bundle[0].parent / 'scene.Data'
    extra.mkdir()
    (extra / 'stale.dat').write_bytes(b'STALE')
    unrelated = bundle[0].parent / 'keep.txt'
    unrelated.write_bytes(b'KEEP')
    (bundle[1] / 'stale.dat').write_bytes(b'STALE')
    restore(bundle)
    assert bundle[0].read_bytes() == b'GOOD PROJECT'
    assert (bundle[1] / 'state.dat').read_bytes() == b'GOOD DATA'
    assert (bundle[1] / 'empty').is_dir()
    assert not (bundle[1] / 'stale.dat').exists()
    assert not extra.exists()
    assert unrelated.read_bytes() == b'KEEP'
    assert checkpoint.is_dir()


def test_restore_can_recover_missing_live_project_from_valid_checkpoint(bundle):
    snapshot(bundle)
    bundle[0].unlink()
    shutil.rmtree(bundle[1])
    restore(bundle)
    assert bundle[0].read_bytes() == b'GOOD PROJECT'


def test_unknown_disk_space_fails_closed(bundle, monkeypatch):
    snapshot(bundle)
    changed_live(bundle)

    def fail(*args):
        raise OSError('disk unavailable')

    monkeypatch.setattr(cp.shutil, 'disk_usage', fail)
    with pytest.raises(RuntimeError, match='cannot establish free space'):
        restore(bundle)
    assert_current(bundle)


@pytest.mark.parametrize('where', ['source', 'checkpoint'])
def test_hardlinked_file_refused(bundle, tmp_path, where):
    checkpoint = snapshot(bundle)
    changed_live(bundle)
    target = bundle[0] if where == 'source' else checkpoint / 'scene.rsproj'
    os.link(target, tmp_path / 'alias.rsproj')
    with pytest.raises(ValueError, match='Hardlinked'):
        snapshot(bundle) if where == 'source' else restore(bundle)
    assert_current(bundle)


def test_symlink_checkpoint_tag_refused(bundle):
    checkpoint = snapshot(bundle)
    alias = bundle[2] / 'alias'
    try:
        alias.symlink_to(checkpoint, target_is_directory=True)
    except OSError:
        pytest.skip('Windows symlink creation unavailable; hardlink tests remain active')
    with pytest.raises(ValueError, match='Alias/reparse'):
        cp.restore_scene(str(bundle[0]), str(bundle[2]), 'alias', LOG)


def test_prune_retains_unvalidated_and_recovery_directories(bundle):
    snapshot(bundle)
    root = bundle[2]
    cp.checkpoint_scene(str(bundle[0]), str(root), 'obsolete', LOG)
    for name in ('legacy', '.scene-recovery-kept'):
        (root / name).mkdir()
        (root / name / 'keep').write_bytes(b'KEEP')
    cp.prune_checkpoints(str(root), {'initial'}, LOG)
    assert (root / 'initial').is_dir()
    assert not (root / 'obsolete').exists()
    assert (root / 'legacy' / 'keep').read_bytes() == b'KEEP'
    assert (root / '.scene-recovery-kept' / 'keep').read_bytes() == b'KEEP'


def test_post_install_hash_failure_restores_original_bundle(bundle, monkeypatch):
    snapshot(bundle)
    changed_live(bundle)
    real_replace = cp.os.replace

    def corrupt_install(source, target):
        result = real_replace(source, target)
        if Path(source).parent.name.startswith('.scene-restore-') and Path(target) == bundle[1]:
            (Path(target) / 'state.dat').write_bytes(b'CORRUPTED AFTER INSTALL')
        return result

    monkeypatch.setattr(cp.os, 'replace', corrupt_install)
    with pytest.raises(RuntimeError, match='Committed restore differs'):
        restore(bundle)
    assert_current(bundle)


def test_failed_removal_of_new_member_never_overwrites_original_backup(bundle, monkeypatch):
    snapshot(bundle)
    changed_live(bundle)
    real_replace = cp.os.replace

    def fail(source, target):
        source, target = Path(source), Path(target)
        if source.parent.name.startswith('.scene-restore-') and source.name == 'scene':
            raise OSError('install failure')
        if source == bundle[0] and target.parent.name.startswith('.scene-restore-'):
            raise OSError('cannot move new project away')
        return real_replace(source, target)

    monkeypatch.setattr(cp.os, 'replace', fail)
    with pytest.raises(RuntimeError, match='occupied recovery target'):
        restore(bundle)
    backup = list(bundle[0].parent.glob('.scene-recovery-*'))[0]
    assert (backup / 'scene.rsproj').read_bytes() == b'CURRENT PROJECT'
    assert (bundle[1] / 'state.dat').read_bytes() == b'CURRENT DATA'
    assert bundle[0].read_bytes() == b'GOOD PROJECT'


def test_live_mutation_during_staging_is_not_overwritten(bundle, monkeypatch):
    snapshot(bundle)
    changed_live(bundle)
    real_copy = cp._copy

    def copy_and_mutate(*args, **kwargs):
        real_copy(*args, **kwargs)
        bundle[0].write_bytes(b'CONCURRENT WRITER')

    monkeypatch.setattr(cp, '_copy', copy_and_mutate)
    with pytest.raises(RuntimeError, match='Live scene changed'):
        restore(bundle)
    assert bundle[0].read_bytes() == b'CONCURRENT WRITER'
    assert (bundle[1] / 'state.dat').read_bytes() == b'CURRENT DATA'


@pytest.mark.parametrize('where', ['source', 'checkpoint', 'root'])
def test_directory_alias_refused_without_touching_target(bundle, tmp_path, where):
    checkpoint = snapshot(bundle)
    changed_live(bundle)
    target = tmp_path / 'external'
    target.mkdir()
    (target / 'keep').write_bytes(b'KEEP')
    alias = (bundle[1] / 'alias' if where == 'source' else
             checkpoint / 'scene' / 'alias' if where == 'checkpoint' else tmp_path / 'alias-root')
    try:
        alias.symlink_to(bundle[2] if where == 'root' else target, target_is_directory=True)
    except OSError:
        pytest.skip('Windows directory symlink creation unavailable')
    with pytest.raises(ValueError, match='Alias/reparse'):
        if where == 'source':
            snapshot(bundle)
        elif where == 'checkpoint':
            restore(bundle)
        else:
            cp.restore_scene(str(bundle[0]), str(alias), 'initial', LOG)
    assert_current(bundle)
    assert (target / 'keep').read_bytes() == b'KEEP'
