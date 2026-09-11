from dataclasses import asdict
import json
from pathlib import Path

from PIL import Image, ImageFile
import pytest

from modules import inventory_checkpoint as checkpoint
from modules import source_inventory as inventory

WINDOW = dict(launch='2025-05-24T00:00:00Z', recovery='2025-05-24T02:00:00Z')


def photo(path, color='white', size=(16, 12)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', size, color).save(path)
    return path


def setup_source(tmp_path, count=3):
    source, cache = tmp_path / 'source', tmp_path / 'checkpoint'
    for number, color in enumerate(('white', 'black', 'red')[:count]):
        photo(source / 'images' / f'camlower_20250524T01000{number}Z.jpg', color)
    return source, cache


def run(source, cache, **kwargs):
    return checkpoint.scan_inventory(source, cache, **WINDOW, **kwargs)


def record_path(cache):
    return next(cache.glob('*/records.jsonl'))


def read_state(cache):
    return json.loads((cache / 'state.json').read_text())['payload']


def count_loads(monkeypatch):
    loads = []
    original = Image.open

    def opened(*args, **kwargs):
        result = original(*args, **kwargs)
        load = result.load

        def counted(*a, **kw):
            loads.append(str(args[0]))
            return load(*a, **kw)
        result.load = counted
        return result

    monkeypatch.setattr(Image, 'open', opened)
    return loads


def test_complete_then_resume_reads_metadata_but_reuses_hashes_and_full_decodes(tmp_path, monkeypatch):
    source, cache = setup_source(tmp_path)
    loads = count_loads(monkeypatch)
    first = run(source, cache)
    assert len(loads) == 3
    assert first.hashing_complete is True and first.verification_complete is True
    token = inventory.approval_token(first)
    journal_size = record_path(cache).stat().st_size

    def no_hash(*args, **kwargs):
        pytest.fail('completed source content must not be rehashed')
    monkeypatch.setattr(inventory, 'file_hash', no_hash)
    events = []
    second = run(source, cache, progress=lambda *event: events.append(event))
    assert len(loads) == 3
    assert inventory.approval_token(second) == token
    assert record_path(cache).stat().st_size == journal_size
    assert {event[0] for event in events} == {'scan', 'hash', 'verify', 'complete'}
    assert events[-1] == ('complete', 3, 3, '')


def test_cancel_during_hash_saves_completed_files_and_rehashes_only_remainder(tmp_path, monkeypatch):
    source, cache = setup_source(tmp_path)
    stop = False
    seen = []
    scanner = inventory.scan_source

    def capture(*args):
        value = scanner(*args)
        seen.append(value)
        return value

    def progress(stage, done, total, path):
        nonlocal stop
        stop = stage == 'hash' and done == 1

    monkeypatch.setattr(inventory, 'scan_source', capture)
    with pytest.raises(InterruptedError):
        run(source, cache, cancelled=lambda: stop, progress=progress)
    assert not seen[0].hashing_complete and not seen[0].verification_complete
    with pytest.raises(ValueError, match='fully hashed'):
        inventory.approval_token(seen[0])
    assert not read_state(cache)['verification_complete']
    original = inventory.file_hash
    hashed = []

    def traced(path, **kwargs):
        hashed.append(str(path))
        return original(path, **kwargs)
    monkeypatch.setattr(inventory, 'file_hash', traced)
    result = run(source, cache)
    assert len(hashed) == 2 and result.verification_complete


def test_cancel_decode_reuses_successful_pixel_proof_only(tmp_path, monkeypatch):
    source, cache = setup_source(tmp_path)
    loads = count_loads(monkeypatch)
    stop = False

    def progress(stage, done, total, path):
        nonlocal stop
        if stage == 'verify' and done == 1:
            stop = True

    with pytest.raises(InterruptedError):
        run(source, cache, cancelled=lambda: stop, progress=progress)
    assert len(loads) == 1
    run(source, cache)
    assert len(loads) == 3


def test_crash_torn_final_record_is_redone_without_discarding_committed_records(tmp_path, monkeypatch):
    source, cache = setup_source(tmp_path)

    def crash(stage, done, total, path):
        if stage == 'hash' and done == 1:
            raise RuntimeError('simulated crash after journal append')

    with pytest.raises(RuntimeError, match='simulated crash'):
        run(source, cache, progress=crash)
    journal = record_path(cache)
    committed = journal.read_bytes()
    with journal.open('ab') as handle:
        handle.write(b'{"payload":')
    original = inventory.file_hash
    hashes = []

    def traced(path, **kwargs):
        hashes.append(path)
        return original(path, **kwargs)
    monkeypatch.setattr(inventory, 'file_hash', traced)
    assert run(source, cache).verification_complete
    assert len(hashes) == 2
    assert journal.read_bytes().startswith(committed)


@pytest.mark.parametrize('change', ['add', 'modify', 'remove', 'noise'])
def test_changed_source_starts_fresh_generation_without_reusing_stale_hashes(tmp_path, monkeypatch, change):
    source, cache = setup_source(tmp_path)
    first = run(source, cache)
    if change == 'add':
        photo(source / 'new_layout/camupper_20250524T010005Z.jpg')
    elif change == 'modify':
        photo(Path(first[0].path), 'blue')
    elif change == 'remove':
        Path(first[0].path).unlink()
    else:
        (source / 'new_delivery.txt').write_text('added')
    original = inventory.file_hash
    hashes = []

    def traced(path, **kwargs):
        hashes.append(path)
        return original(path, **kwargs)
    monkeypatch.setattr(inventory, 'file_hash', traced)
    second = run(source, cache)
    assert len(hashes) == len(second)
    assert first.source_fingerprint != second.source_fingerprint
    assert len(list(cache.glob('*/snapshot.json'))) == 2


def test_changed_window_reuses_content_but_recomputes_findings_and_token(tmp_path, monkeypatch):
    source, cache = setup_source(tmp_path)
    first = run(source, cache)
    token = inventory.approval_token(first)

    def no_hash(*args, **kwargs):
        pytest.fail('window change must not require content rehash')
    monkeypatch.setattr(inventory, 'file_hash', no_hash)
    second = checkpoint.scan_inventory(source, cache, launch='2025-05-24T01:30:00Z',
                                       recovery='2025-05-24T02:00:00Z')
    assert all(item.window_status == 'outside_window' for item in second)
    assert inventory.approval_token(second) != token
    assert len(list(cache.glob('*/snapshot.json'))) == 1


@pytest.mark.parametrize('target', ['owner', 'snapshot', 'journal'])
def test_malformed_or_altered_cache_is_refused(tmp_path, target):
    source, cache = setup_source(tmp_path)
    run(source, cache)
    path = (cache / 'owner.json' if target == 'owner' else
            next(cache.glob('*/snapshot.json')) if target == 'snapshot' else record_path(cache))
    raw = path.read_bytes()
    path.write_bytes(raw.replace(b'"sha256":"', b'"sha256":"f', 1))
    with pytest.raises(checkpoint.CheckpointError, match='Malformed|altered'):
        run(source, cache)


@pytest.mark.parametrize('bad_path', ['../escape.jpg', '/absolute.jpg', 'images\\bad.jpg', 'missing.jpg'])
def test_rechecksummed_journal_cannot_inject_paths(tmp_path, bad_path):
    source, cache = setup_source(tmp_path)
    run(source, cache)
    journal = record_path(cache)
    lines = journal.read_bytes().splitlines()
    value = json.loads(lines[0])['payload']
    value['path'] = bad_path
    journal.write_bytes(checkpoint._encoded({'payload': value, 'sha256': checkpoint._digest(value)}) + b'\n')
    with pytest.raises(checkpoint.CheckpointError, match='path/hash'):
        run(source, cache)


def test_rechecksummed_snapshot_must_equal_fresh_scan(tmp_path):
    source, cache = setup_source(tmp_path)
    run(source, cache)
    path = next(cache.glob('*/snapshot.json'))
    value = json.loads(path.read_bytes())['payload']
    value['items'].pop()
    checkpoint._atomic(path, value)
    with pytest.raises(checkpoint.CheckpointError, match='fresh source'):
        run(source, cache)


def test_cross_source_cache_is_rejected(tmp_path):
    source, cache = setup_source(tmp_path)
    run(source, cache)
    other = tmp_path / 'other'
    photo(other / 'camlower_20250524T010000Z.jpg')
    with pytest.raises(checkpoint.CheckpointError, match='another source'):
        run(other, cache)


@pytest.mark.parametrize('placement', ['inside', 'ancestor'])
def test_checkpoint_cannot_overlap_source(tmp_path, placement):
    source, _ = setup_source(tmp_path)
    cache = source / 'cache' if placement == 'inside' else tmp_path
    with pytest.raises(checkpoint.CheckpointError, match='disjoint'):
        run(source, cache)
    assert not (source / 'cache').exists()


def test_unowned_checkpoint_directory_is_not_overwritten(tmp_path):
    source, cache = setup_source(tmp_path)
    cache.mkdir()
    (cache / 'unrelated.txt').write_text('keep')
    with pytest.raises(checkpoint.CheckpointError, match='unowned'):
        run(source, cache)
    assert (cache / 'unrelated.txt').read_text() == 'keep'


def test_exclusive_writer_lock(tmp_path):
    source, cache = setup_source(tmp_path)
    cache.mkdir()
    with checkpoint._locked(cache):
        with pytest.raises(checkpoint.CheckpointError, match='active writer'):
            run(source, cache)


def test_verification_version_change_requires_full_decode_again(tmp_path, monkeypatch):
    source, cache = setup_source(tmp_path)
    loads = count_loads(monkeypatch)
    run(source, cache)
    assert len(loads) == 3
    monkeypatch.setattr(inventory, 'IMAGE_VERIFICATION_VERSION', 'future-full-pixel-decode')
    run(source, cache)
    assert len(loads) == 6


def test_header_valid_truncated_jpeg_fails_full_decode_and_is_not_cached(tmp_path):
    source, cache = setup_source(tmp_path, 1)
    path = next(source.rglob('*.jpg'))
    Image.effect_noise((128, 128), 60).convert('RGB').save(path)
    path.write_bytes(path.read_bytes()[:-30])
    with Image.open(path) as image:
        image.verify()  # Regression: this accepts the corrupt pixel payload.
    result = run(source, cache)
    assert 'Unreadable image' in result[0].exception
    assert 'truncated' in result[0].exception.lower()
    assert b'"kind":"decode"' not in record_path(cache).read_bytes()
    again = run(source, cache)
    assert again[0].exception == result[0].exception


def test_identical_payloads_decode_once_but_mask_dimensions_are_always_checked(tmp_path, monkeypatch):
    source, cache = setup_source(tmp_path, 1)
    path = next(source.rglob('*.jpg'))
    duplicate = path.parent / 'zone2' / path.name
    duplicate.parent.mkdir()
    duplicate.write_bytes(path.read_bytes())
    photo(path.with_name(path.name + '.mask.png'), size=(8, 8))
    loads = count_loads(monkeypatch)
    first = run(source, cache)
    assert len(loads) == 2  # One JPEG payload and one PNG payload.
    assert any('Mask dimensions differ' in item.exception for item in first)
    second = run(source, cache)
    assert len(loads) == 2
    assert [asdict(i) for i in second] == [asdict(i) for i in first]


def test_pixel_limit_and_global_truncated_loading_cannot_weaken_verification(tmp_path, monkeypatch):
    source, cache = setup_source(tmp_path, 1)
    monkeypatch.setattr(inventory, 'MAX_VERIFICATION_PIXELS', 100)
    result = run(source, cache)
    assert 'pixel limit' in result[0].exception
    monkeypatch.setattr(ImageFile, 'LOAD_TRUNCATED_IMAGES', True)
    with pytest.raises(ValueError, match='truncated-image loading disabled'):
        run(source, cache)
    assert not read_state(cache)['verification_complete']


@pytest.mark.parametrize('stage', ['scan', 'hash', 'verify', 'complete'])
def test_callback_failure_never_persists_complete_flags(tmp_path, stage):
    source, cache = setup_source(tmp_path, 1)

    def fail(current, done, total, path):
        if current == stage and (done == total or stage == 'scan'):
            raise RuntimeError('callback failed')
    with pytest.raises(RuntimeError, match='callback failed'):
        run(source, cache, progress=fail)
    assert not read_state(cache)['hashing_complete']
    assert not read_state(cache)['verification_complete']


@pytest.mark.parametrize('changed_stage', ['verify', 'complete'])
def test_change_during_verification_refuses_completion(tmp_path, changed_stage):
    source, cache = setup_source(tmp_path)

    def mutate(stage, done, total, path):
        if (stage == changed_stage and
                (changed_stage == 'complete' or done == 1)):
            (source / 'arrived.txt').write_text('source changed')
    with pytest.raises(ValueError, match='Source tree changed'):
        run(source, cache, progress=mutate)
    assert not read_state(cache)['verification_complete']


def test_snapshot_written_once_not_per_file_or_on_resume(tmp_path, monkeypatch):
    source, cache = setup_source(tmp_path)
    writes = []
    original = checkpoint._atomic

    def traced(path, payload):
        writes.append(path.name)
        return original(path, payload)
    monkeypatch.setattr(checkpoint, '_atomic', traced)
    run(source, cache)
    run(source, cache)
    assert writes.count('snapshot.json') == 1


def test_atomic_writer_uses_shared_reader_lock_retry(tmp_path, monkeypatch):
    from module_base import atomic_io
    target = tmp_path / 'state.json'
    checkpoint._atomic(target, {'state': 'old'})
    original = atomic_io.os.replace
    calls = []

    def briefly_shared(source, destination):
        calls.append(1)
        if len(calls) == 1:
            error = PermissionError('shared by reader')
            error.winerror = 5
            raise error
        assert json.loads(target.read_bytes())['payload'] == {'state': 'old'}
        original(source, destination)
    monkeypatch.setattr(atomic_io.os, 'replace', briefly_shared)
    monkeypatch.setattr(atomic_io.time, 'sleep', lambda seconds: None)
    checkpoint._atomic(target, {'state': 'new'})
    assert len(calls) == 2
    assert json.loads(target.read_bytes())['payload'] == {'state': 'new'}


def test_failure_state_sharing_does_not_hide_original_or_discard_hashes(tmp_path, monkeypatch):
    source, cache = setup_source(tmp_path)
    original = checkpoint._atomic
    fail_state = False

    def atomic(path, value):
        if fail_state and path.name == 'state.json':
            raise PermissionError('state is still shared')
        original(path, value)

    def failed_progress(stage, done, total, path):
        nonlocal fail_state
        if stage == 'hash' and done == 1:
            fail_state = True
            raise RuntimeError('original progress failure')
    monkeypatch.setattr(checkpoint, '_atomic', atomic)
    with pytest.raises(RuntimeError, match='original progress failure') as caught:
        run(source, cache, progress=failed_progress)
    assert any('state is still shared' in note for note in caught.value.__notes__)
    rows = record_path(cache).read_bytes().splitlines()
    assert len(rows) == 1 and json.loads(rows[0])['payload']['kind'] == 'hash'
    fail_state = False
    assert run(source, cache).verification_complete


def test_completion_callback_cannot_obtain_approval_token(tmp_path, monkeypatch):
    source, cache = setup_source(tmp_path)
    captured = []
    original = inventory.scan_source

    def scan(*args):
        value = original(*args)
        captured.append(value)
        return value

    def progress(stage, done, total, path):
        if captured:
            with pytest.raises(ValueError, match='fully hashed'):
                inventory.approval_token(captured[0])
    monkeypatch.setattr(inventory, 'scan_source', scan)
    result = run(source, cache, progress=progress)
    assert inventory.approval_token(result)


def test_case_insensitive_source_path_collision_refused(tmp_path, monkeypatch):
    from dataclasses import replace
    source, cache = setup_source(tmp_path, 1)
    original = inventory.scan_source

    def collision(*args):
        result = original(*args)
        result.append(replace(result[0], relative_path=result[0].relative_path.upper()))
        return result
    monkeypatch.setattr(inventory, 'scan_source', collision)
    with pytest.raises(checkpoint.CheckpointError, match='path collisions'):
        run(source, cache)


def test_hardlinked_cache_file_refused_without_modifying_external_file(tmp_path):
    import os
    source, cache = setup_source(tmp_path)
    run(source, cache)
    external = tmp_path / 'external.json'
    os.link(cache / 'owner.json', external)
    before = external.read_bytes()
    with pytest.raises(checkpoint.CheckpointError, match='hardlinked'):
        run(source, cache)
    assert external.read_bytes() == before


def test_crash_before_snapshot_commit_recovers_empty_generation(tmp_path):
    source, cache = setup_source(tmp_path)
    first = run(source, cache)
    generation = record_path(cache).parent
    # Reconstruct the precise mkdir-before-snapshot crash state in this fixture.
    (generation / 'records.jsonl').unlink()
    (generation / 'snapshot.json').unlink()
    (generation / ('snapshot.json.' + 'a' * 32 + '.partial')).write_bytes(b'{')
    result = run(source, cache)
    assert result.verification_complete
    assert inventory.approval_token(result) == inventory.approval_token(first)


def test_actual_process_exit_resumes_durable_hash_record(tmp_path, monkeypatch):
    import subprocess
    import sys
    source, cache = setup_source(tmp_path)
    code = '''
import os, sys
from modules import inventory_checkpoint as cp
cp.JOURNAL_FLUSH_RECORDS = 1
def progress(stage, done, total, path):
    if stage == 'hash' and done == 1:
        os._exit(17)
cp.scan_inventory(sys.argv[1], sys.argv[2], launch=sys.argv[3], recovery=sys.argv[4], progress=progress)
'''
    result = subprocess.run([sys.executable, '-c', code, str(source), str(cache),
                             WINDOW['launch'], WINDOW['recovery']], capture_output=True, timeout=60)
    assert result.returncode == 17, result.stderr.decode(errors='replace')
    assert not read_state(cache)['verification_complete']
    original = inventory.file_hash
    hashes = []

    def traced(path, **kwargs):
        hashes.append(path)
        return original(path, **kwargs)
    monkeypatch.setattr(inventory, 'file_hash', traced)
    assert run(source, cache).verification_complete
    assert len(hashes) == 2


def donor_artifacts(source, tmp_path, count=2):
    import hashlib
    items = inventory.scan_source(source)
    inventory.hash_identities(items)
    snapshot, journal = tmp_path / 'donor_snapshot.json', tmp_path / 'donor_hashes.jsonl'
    snapshot.write_text(json.dumps(dict(source_root=items.source_root,
        fingerprint=items.source_fingerprint, items=[asdict(item) for item in items],
        verification_complete=True, verification_version='old-header-only')), encoding='utf-8')
    journal.write_text(''.join(json.dumps({'path': item.path, 'sha256': item.sha256}) + '\n'
                               for item in items[:count]), encoding='utf-8')
    return checkpoint.HashJournalImport(snapshot, journal,
        hashlib.sha256(snapshot.read_bytes()).hexdigest(), hashlib.sha256(journal.read_bytes()).hexdigest())


def test_pinned_hash_import_skips_prior_reads_but_never_imports_old_decode_claims(tmp_path, monkeypatch):
    source, cache = setup_source(tmp_path)
    donor = donor_artifacts(source, tmp_path)
    original = inventory.file_hash
    hashed = []
    loads = count_loads(monkeypatch)

    def traced(path, **kwargs):
        hashed.append(path)
        return original(path, **kwargs)
    monkeypatch.setattr(inventory, 'file_hash', traced)
    events = []
    result = run(source, cache, hash_import=donor, progress=lambda *row: events.append(row))
    assert len(hashed) == 1 and len(loads) == 3
    assert result.verification_complete and inventory.approval_token(result)
    assert len([row for row in events if row[0] == 'import']) == 2
    assert next(cache.glob('*/hash_import.json')).is_file()
    run(source, cache)
    assert len(hashed) == 1 and len(loads) == 3


@pytest.mark.parametrize('which', ['snapshot', 'journal'])
def test_hash_import_requires_exact_pinned_artifact_bytes(tmp_path, which):
    source, cache = setup_source(tmp_path)
    donor = donor_artifacts(source, tmp_path)
    path = Path(getattr(donor, which))
    path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(checkpoint.CheckpointError, match='pinned hash'):
        run(source, cache, hash_import=donor)
    assert record_path(cache).stat().st_size == 0


@pytest.mark.parametrize('problem', ['source', 'fingerprint', 'identity', 'duplicate_item', 'journal_path', 'conflicting_hash', 'malformed'])
def test_rechecksummed_donor_still_requires_matching_metadata_and_valid_records(tmp_path, problem):
    import hashlib
    source, cache = setup_source(tmp_path)
    donor = donor_artifacts(source, tmp_path)
    snapshot = json.loads(Path(donor.snapshot).read_bytes())
    rows = [json.loads(line) for line in Path(donor.journal).read_bytes().splitlines()]
    if problem == 'source':
        snapshot['source_root'] = str(tmp_path / 'elsewhere')
    elif problem == 'fingerprint':
        snapshot['fingerprint'] = 'f' * 64
    elif problem == 'identity':
        snapshot['items'][0]['mtime_ns'] += 1
    elif problem == 'duplicate_item':
        snapshot['items'].append(snapshot['items'][0])
    elif problem == 'journal_path':
        rows[0]['path'] = '../not-an-image.jpg'
    elif problem == 'conflicting_hash':
        rows.append({**rows[0], 'sha256': 'b' * 64})
    Path(donor.snapshot).write_text(json.dumps(snapshot), encoding='utf-8')
    Path(donor.journal).write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
    if problem == 'malformed':
        with Path(donor.journal).open('ab') as handle:
            handle.write(b'{')
    changed = checkpoint.HashJournalImport(donor.snapshot, donor.journal,
        hashlib.sha256(Path(donor.snapshot).read_bytes()).hexdigest(),
        hashlib.sha256(Path(donor.journal).read_bytes()).hexdigest())
    with pytest.raises(checkpoint.CheckpointError):
        run(source, cache, hash_import=changed)
    assert record_path(cache).stat().st_size == 0


def test_cancelled_import_resumes_durable_seed_without_donor(tmp_path, monkeypatch):
    source, cache = setup_source(tmp_path)
    donor = donor_artifacts(source, tmp_path)
    stop = False

    def progress(stage, done, total, path):
        nonlocal stop
        stop = stage == 'import' and done == 1
    with pytest.raises(InterruptedError):
        run(source, cache, hash_import=donor, cancelled=lambda: stop, progress=progress)
    original = inventory.file_hash
    hashed = []

    def traced(path, **kwargs):
        hashed.append(path)
        return original(path, **kwargs)
    monkeypatch.setattr(inventory, 'file_hash', traced)
    assert run(source, cache).verification_complete
    assert len(hashed) == 2
