"""Resumable source census; checkpoint data never supplies approval or decisions."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import time
from uuid import uuid4

import PIL

from module_base.atomic_io import replace_file
from . import source_inventory as inventory

SCHEMA = 1
JOURNAL_FLUSH_RECORDS = 64
JOURNAL_FLUSH_SECONDS = 1.0
MAX_RECORD_BYTES = 262144


class CheckpointError(ValueError):
    """Checkpoint identity, schema, path, or integrity validation failed."""


@dataclass(frozen=True)
class HashJournalImport:
    """Explicitly trusted donor artifacts; byte hashes must be pinned by caller.

    Snapshot: SourceInventory metadata with source_root, fingerprint, items.
    Journal: JSONL {path, sha256} records. Only hashes are imported, never old
    decode claims, decisions, exceptions, timestamps, or approval/completion flags.
    """
    snapshot: str | Path
    journal: str | Path
    snapshot_sha256: str
    journal_sha256: str


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('utf-8')


def _digest(value):
    return hashlib.sha256(_encoded(value)).hexdigest()


def _hex(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _safe(path: Path):
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise CheckpointError(f'Checkpoint/source path contains a link: {part}')
    if path.exists() and path.is_file() and path.stat().st_nlink != 1:
        raise CheckpointError(f'Checkpoint file must not be hardlinked: {path}')


def _atomic(path, payload):
    _safe(path)
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.partial')
    try:
        with temporary.open('xb') as handle:
            handle.write(_encoded({'payload': payload, 'sha256': _digest(payload)}))
            handle.flush()
            os.fsync(handle.fileno())
        _safe(path)
        replace_file(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()  # Only this call's own incomplete cache write.


def _unpack(raw):
    try:
        value = json.loads(raw)
        if (not isinstance(value, dict) or set(value) != {'payload', 'sha256'}
                or not _hex(value['sha256']) or _digest(value['payload']) != value['sha256']):
            raise ValueError('checksum or envelope')
        return value['payload'], value['sha256']
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise CheckpointError('Malformed or altered checkpoint record') from exc


def _read(path, limit):
    _safe(path)
    if not path.is_file() or path.stat().st_size > limit:
        raise CheckpointError(f'Invalid checkpoint size/type: {path}')
    return _unpack(path.read_bytes())[0]


@contextmanager
def _locked(root):
    path = root / 'inventory.lock'
    _safe(path)
    with path.open('a+b') as handle:
        try:
            # Reading the locked byte itself fails on Windows before locking()
            # can report contention. fstat works without touching that byte.
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise CheckpointError('Inventory checkpoint already has an active writer') from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class _DecodeProofs(dict):
    def __init__(self):
        super().__init__()
        self.by_digest = {}

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.by_digest[key[0]] = key[1:]


class _Journal:
    """Checksummed, chained records; only an uncommitted final line is discarded."""

    def __init__(self, path, snapshot_hash, items, version, cancelled):
        self.path, self.chain, self.version = path, snapshot_hash, version
        self.hashes, self.proofs, self.verified_paths = {}, _DecodeProofs(), set()
        self.pending, self.flushed_at = 0, time.monotonic()
        by_path = {item.relative_path: item for item in items}
        _safe(path)
        if path.exists():
            with path.open('r+b') as handle:
                while True:
                    inventory._check_cancelled(cancelled)
                    start = handle.tell()
                    raw = handle.readline(MAX_RECORD_BYTES + 1)
                    if not raw:
                        break
                    if len(raw) > MAX_RECORD_BYTES:
                        raise CheckpointError('Oversized checkpoint journal record')
                    if not raw.endswith(b'\n'):
                        # This exact private journal's interrupted append is not
                        # evidence. Keep every committed record and redo this one.
                        handle.truncate(start)
                        handle.flush()
                        os.fsync(handle.fileno())
                        break
                    row, checksum = _unpack(raw)
                    if not isinstance(row, dict) or row.get('previous') != self.chain:
                        raise CheckpointError('Checkpoint journal chain mismatch')
                    rel, digest = row.get('path'), row.get('sha256')
                    if not isinstance(rel, str) or rel not in by_path or not _hex(digest):
                        raise CheckpointError('Checkpoint journal path/hash mismatch')
                    if row.get('kind') == 'hash' and set(row) == {'previous', 'kind', 'path', 'sha256'}:
                        if rel in self.hashes and self.hashes[rel] != digest:
                            raise CheckpointError('Conflicting cached hashes for one file')
                        self.hashes[rel] = digest
                    elif row.get('kind') == 'decode' and set(row) == {
                            'previous', 'kind', 'path', 'sha256', 'width', 'height', 'version'}:
                        if (self.hashes.get(rel) != digest or by_path[rel].kind not in ('image', 'mask')
                                or not isinstance(row['version'], str)
                                or any(type(row[k]) is not int or not 0 < row[k] <= 2**31-1
                                       for k in ('width', 'height'))):
                            raise CheckpointError('Decode proof is not bound to a valid file hash/dimensions')
                        if row['version'] == version:
                            size = row['width'], row['height']
                            if digest in self.proofs.by_digest and self.proofs.by_digest[digest] != size:
                                raise CheckpointError('Conflicting dimensions for identical content')
                            self.proofs[(digest, *size)] = True
                            self.verified_paths.add(rel)
                    else:
                        raise CheckpointError('Unknown checkpoint journal schema')
                    self.chain = checksum
        self.handle = path.open('ab')

    def append(self, **row):
        row['previous'] = self.chain
        checksum = _digest(row)
        raw = _encoded({'payload': row, 'sha256': checksum}) + b'\n'
        if len(raw) > MAX_RECORD_BYTES:
            raise CheckpointError('Oversized checkpoint journal record')
        self.handle.write(raw)
        self.chain = checksum
        self.pending += 1
        if self.pending >= JOURNAL_FLUSH_RECORDS or time.monotonic() - self.flushed_at >= JOURNAL_FLUSH_SECONDS:
            self.flush()

    def flush(self):
        self.handle.flush()
        os.fsync(self.handle.fileno())
        self.pending, self.flushed_at = 0, time.monotonic()

    def close(self):
        try:
            self.flush()
        finally:
            self.handle.close()


def _import_hashes(items, journal, donor, emit, cancelled):
    if not isinstance(donor, HashJournalImport):
        raise CheckpointError('Hash import requires explicit pinned donor artifacts')

    def artifact(path, expected):
        inventory._check_cancelled(cancelled)
        path = Path(path)
        _safe(path)
        if not _hex(expected) or not path.is_file() or path.stat().st_size > 1024**3:
            raise CheckpointError('Invalid donor artifact/digest or artifact larger than 1 GiB')
        before = inventory._identity(path.stat())
        raw = path.read_bytes()
        if inventory._identity(path.stat()) != before or hashlib.sha256(raw).hexdigest() != expected:
            raise CheckpointError('Donor artifact differs from its pinned hash')
        inventory._check_cancelled(cancelled)
        return raw

    try:
        snapshot = json.loads(artifact(donor.snapshot, donor.snapshot_sha256))
        if (not isinstance(snapshot, dict) or snapshot.get('source_root') != items.source_root
                or snapshot.get('fingerprint') != items.source_fingerprint
                or not isinstance(snapshot.get('items'), list)):
            raise CheckpointError('Donor snapshot source/fingerprint differs from fresh scan')
        by_path = {item.path: item for item in items}
        identity_fields = ('device', 'file_id', 'size_bytes', 'mtime_ns', 'ctime_ns')
        donor_paths = set()
        for row in snapshot['items']:
            inventory._check_cancelled(cancelled)
            if not isinstance(row, dict) or not isinstance(row.get('path'), str):
                raise CheckpointError('Malformed donor snapshot item')
            path = row['path']
            current = by_path.get(path)
            if (current is None or path in donor_paths
                    or row.get('relative_path') != current.relative_path
                    or any(type(row.get(key)) is not int or row[key] != getattr(current, key)
                           for key in identity_fields)):
                raise CheckpointError('Donor item path/identity differs from fresh scan')
            donor_paths.add(path)
        imported = {}
        for raw in artifact(donor.journal, donor.journal_sha256).splitlines():
            inventory._check_cancelled(cancelled)
            if not raw.strip():
                continue
            row = json.loads(raw)
            if (not isinstance(row, dict) or set(row) != {'path', 'sha256'}
                    or not isinstance(row['path'], str) or row['path'] not in donor_paths
                    or not _hex(row['sha256'])):
                raise CheckpointError('Invalid donor hash record/path')
            rel = by_path[row['path']].relative_path
            digest = row['sha256']
            if ((rel in imported and imported[rel] != digest)
                    or (rel in journal.hashes and journal.hashes[rel] != digest)):
                raise CheckpointError('Conflicting donor/cached content hashes')
            imported[rel] = digest
    except (TypeError, KeyError, json.JSONDecodeError) as exc:
        raise CheckpointError('Malformed donor artifact') from exc
    # Validate every record before persisting any donor evidence. No source image
    # bytes are reread here: trust in the pinned donor's producer is explicit.
    for done, (rel, digest) in enumerate(sorted(imported.items()), 1):
        if rel not in journal.hashes:
            journal.append(kind='hash', path=rel, sha256=digest)
            journal.hashes[rel] = digest
        emit('import', done, len(imported), rel)
    journal.flush()


def scan_inventory(source, checkpoint_dir, *, launch, recovery, cancelled=None,
                   progress=None, hash_import: HashJournalImport | None = None) -> inventory.SourceInventory:
    """Fresh metadata scan, resumable hashes, then versioned full pixel decoding.

    progress(stage, done, total, path) runs synchronously on the calling worker;
    callback errors propagate. Stages: scan, invalidate, import, hash, verify, complete.
    cancelled() raises InterruptedError. The existing scanner is only cancellable
    at its boundaries; hashing polls within reads, decoding between Pillow calls.
    No approval or include/exclude decisions are loaded from the cache. Both
    completion flags are false on failure; a returned inventory completed all
    passes, but still requires exception review and explicit owner confirmation.
    """
    source, root = Path(source).absolute(), Path(checkpoint_dir).absolute()
    _safe(source)
    _safe(root)
    source, root = source.resolve(strict=True), root.resolve()
    if root.is_relative_to(source) or source.is_relative_to(root):
        raise CheckpointError('Source and checkpoint directories must be disjoint')
    # Validate time bounds before creating any cache files.
    inventory.apply_dive_window([], launch, recovery)
    inventory._check_cancelled(cancelled)
    root.mkdir(parents=True, exist_ok=True)
    with _locked(root):
        owner = {'schema': SCHEMA, 'source': str(source), 'checkpoint_dir': str(root)}
        owner_path = root / 'owner.json'
        if owner_path.exists():
            if _read(owner_path, MAX_RECORD_BYTES) != owner:
                raise CheckpointError('Checkpoint belongs to another source/directory or schema')
        else:
            if any(p.name != 'inventory.lock' for p in root.iterdir()):
                raise CheckpointError('Checkpoint directory contains unowned files')
            _atomic(owner_path, owner)

        def emit(stage, done=0, total=0, path=''):
            inventory._check_cancelled(cancelled)
            if progress is not None:
                progress(stage, done, total, path)
            inventory._check_cancelled(cancelled)

        items, journal = None, None
        state_path = root / 'state.json'
        state = {'schema': SCHEMA, 'hashing_complete': False, 'verification_complete': False}
        _atomic(state_path, state)
        try:
            emit('scan')
            items = inventory.scan_source(source)  # The only scanner; reread metadata every invocation.
            items.hashing_complete = items.verification_complete = False
            emit('scan', len(items), len(items), str(source))
            names = [item.relative_path.casefold() for item in items]
            if len(set(names)) != len(names):
                raise CheckpointError('Source inventory has case-insensitive path collisions')
            snapshot = {'schema': SCHEMA, 'source': str(source),
                        'source_fingerprint': items.source_fingerprint,
                        'items': [asdict(item) for item in items]}
            snapshot_hash = _digest(snapshot)
            generation = root / snapshot_hash
            _safe(generation)
            if not generation.exists():
                emit('invalidate')
                generation.mkdir()
                _atomic(generation / 'snapshot.json', snapshot)
            elif not (generation / 'snapshot.json').exists():
                # A crash between mkdir and the first atomic snapshot has no
                # committed evidence. Recover only this empty/partial generation.
                if any(not re.fullmatch(r'snapshot\.json\.[0-9a-f]{32}\.partial', p.name)
                       for p in generation.iterdir()):
                    raise CheckpointError('Generation lacks its metadata snapshot')
                _atomic(generation / 'snapshot.json', snapshot)
            else:
                saved = _read(generation / 'snapshot.json', len(_encoded(snapshot)) + MAX_RECORD_BYTES)
                if saved != snapshot:
                    raise CheckpointError('Cached metadata differs from the fresh source scan')
            inventory.apply_dive_window(items, launch, recovery)
            version = f'{inventory.IMAGE_VERIFICATION_VERSION}:Pillow-{PIL.__version__}:pixels-{inventory.MAX_VERIFICATION_PIXELS}'
            journal = _Journal(generation / 'records.jsonl', snapshot_hash, items, version, cancelled)
            if hash_import is not None:
                _import_hashes(items, journal, hash_import, emit, cancelled)
                _atomic(generation / 'hash_import.json', {
                    'snapshot_sha256': hash_import.snapshot_sha256,
                    'journal_sha256': hash_import.journal_sha256})
            for item in items:
                item.sha256 = journal.hashes.get(item.relative_path, '')
            state.update(generation=snapshot_hash, source_fingerprint=items.source_fingerprint,
                         dive_window=items.dive_window, verification_version=version)
            _atomic(state_path, state)

            def hash_progress(done, total, path):
                if done:
                    item = items[done-1]
                    rel = item.relative_path
                    if journal.hashes.get(rel) != item.sha256:
                        journal.append(kind='hash', path=rel, sha256=item.sha256)
                        journal.hashes[rel] = item.sha256
                emit('hash', done, total, path)

            emit('hash', 0, len(items))
            inventory.hash_identities(items, cancelled=cancelled, progress=hash_progress, resume=True)
            journal.flush()
            eligible = [item for item in items if item.included and item.kind in ('image', 'mask')]

            def verify_progress(done, total, path):
                if done:
                    item = eligible[done-1]
                    rel = item.relative_path
                    size = journal.proofs.by_digest.get(item.sha256)
                    if size is not None and rel not in journal.verified_paths:
                        journal.append(kind='decode', path=rel, sha256=item.sha256,
                                       width=size[0], height=size[1], version=version)
                        journal.verified_paths.add(rel)
                emit('verify', done, total, path)

            emit('verify', 0, len(eligible))
            inventory.verify_images(items, cancelled=cancelled, progress=verify_progress,
                                    verified_cache=journal.proofs)
            items.verification_complete = False  # Full-pass guard and final callback still pending.
            inventory.assert_source_unchanged(items, cancelled=cancelled)
            finished_journal, journal = journal, None
            finished_journal.close()
            emit('complete', len(items), len(items))
            inventory.assert_source_unchanged(items, cancelled=cancelled)
            items.verification_complete = True
            state.update(hashing_complete=True, verification_complete=True)
            _atomic(state_path, state)
            return items
        except BaseException as exc:
            if items is not None:
                items.hashing_complete = items.verification_complete = False
            state.update(hashing_complete=False, verification_complete=False)
            # Preserve the originating failure even when state/progress readers
            # also temporarily prevent writing the failure report itself.
            try:
                _atomic(state_path, state)
            except OSError as state_error:
                exc.add_note(f'Could not persist incomplete checkpoint state: {state_error}')
            raise
        finally:
            if journal is not None:
                journal.close()
