#!/usr/bin/env python3
"""Hash-validated project-bundle checkpoints and staged, recoverable restore.

Snapshots are file copies, not component export/import round trips. A manifest
proves copied byte identity, not RealityScan project validity. Callers must stop
the scene's writer first: lock markers are a refusal signal; their absence does
not prove application quiescence. No RealityScan process is started here.

The multi-file commit is not crash-atomic. On failure, original bundle members
are restored or retained in the named recovery directory; they are never
deleted to make rollback succeed. Unmanifested legacy checkpoints are refused.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile


MANIFEST = '_checkpoint.json'


def _candidates(scene: Path) -> list[Path]:
    stem = scene.with_suffix('')
    return [scene, stem, Path(str(stem) + '.Data'), Path(str(scene) + '.data')]


def scene_bundle(scene_path: str) -> list[str]:
    """Existing project and supported companion paths (without following links)."""
    return [str(p) for p in _candidates(Path(scene_path)) if os.path.lexists(p)]


def _safe_path(path: Path) -> None:
    """Reject symlinks, junctions/reparse points, hardlinked files and devices."""
    for part in reversed((path, *path.parents)):
        if not os.path.lexists(part):
            continue
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError(f'Alias/reparse path refused: {part}')
        if stat.S_ISREG(info.st_mode):
            if info.st_nlink != 1:
                raise ValueError(f'Hardlinked file refused: {part}')
        elif not stat.S_ISDIR(info.st_mode):
            raise ValueError(f'Non-file/directory refused: {part}')


def _tag(tag: str) -> None:
    reserved = {'CON', 'PRN', 'AUX', 'NUL', 'CLOCK$', 'CONIN$', 'CONOUT$'}
    reserved.update(f'{prefix}{n}' for prefix in ('COM', 'LPT') for n in range(1, 10))
    if (not isinstance(tag, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', tag)
            or tag.endswith('.') or tag.split('.')[0].upper() in reserved):
        raise ValueError(f'Unsafe checkpoint tag: {tag!r}')


def _paths(scene_path: str, checkpoints_dir: str, tag: str) -> tuple[Path, Path, Path]:
    _tag(tag)
    scene = Path(os.path.abspath(scene_path))
    root = Path(os.path.abspath(checkpoints_dir))
    if scene.name == MANIFEST:
        raise ValueError('Project name conflicts with checkpoint manifest')
    for path in (scene, root, root / tag):
        _safe_path(path)
    candidates = _candidates(scene)
    if len({os.path.normcase(str(p)) for p in candidates}) != len(candidates):
        raise ValueError('Project must have an extension and distinct bundle names')
    for member in candidates:
        if root == member or root in member.parents or member in root.parents:
            raise ValueError('Checkpoint root overlaps the live scene bundle')
    return scene, root, root / tag


def _is_lock(name: str) -> bool:
    return name.lower().endswith('.lock')


def _hash(path: Path) -> dict:
    _safe_path(path)
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    after = path.stat()
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    if any(getattr(before, k) != getattr(after, k) for k in fields):
        raise ValueError(f'File changed while hashing: {path}')
    return {'kind': 'file', 'size': after.st_size, 'sha256': digest.hexdigest()}


def _inventory(base: Path, names: list[str], *, ignore_locks: bool = False) -> dict:
    result = {}

    def visit(path: Path) -> None:
        _safe_path(path)
        if ignore_locks and _is_lock(path.name):
            return
        relative = path.relative_to(base).as_posix()
        if path.is_dir():
            result[relative] = {'kind': 'directory'}
            for child in sorted(path.iterdir()):
                visit(child)
        elif path.is_file():
            result[relative] = _hash(path)
        else:
            raise ValueError(f'Missing bundle member: {path}')

    for name in names:
        visit(base / name)
    return result


def _names(scene: Path) -> list[str]:
    names = []
    for index, path in enumerate(_candidates(scene)):
        _safe_path(path)
        if os.path.lexists(path):
            if (index == 0 and not path.is_file()) or (index > 0 and not path.is_dir()):
                raise ValueError(f'Unexpected bundle member type: {path}')
            names.append(path.name)
    return names


def _no_locks(scene: Path) -> None:
    # Refuse even a closed marker: quiescence is unknown.
    adjacent = [scene.parent / '.lock', Path(str(scene) + '.lock'),
                Path(str(scene.with_suffix('')) + '.lock')]
    for path in adjacent:
        if os.path.lexists(path):
            raise RuntimeError(f'REFUSING TO ROLL BACK: scene lock present: {path}')
    for name in _names(scene):
        path = scene.parent / name
        if path.is_dir():
            for directory, dirs, files in os.walk(path, followlinks=False):
                for child in dirs + files:
                    item = Path(directory) / child
                    _safe_path(item)
                    if _is_lock(child):
                        raise RuntimeError(f'REFUSING TO ROLL BACK: scene lock present: {item}')


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate manifest key: {key}')
        result[key] = value
    return result


def _validate(directory: Path, scene: Path) -> dict:
    _safe_path(directory)
    manifest_path = directory / MANIFEST
    _safe_path(manifest_path)
    if not manifest_path.is_file():
        raise ValueError(f'Checkpoint has no manifest: {directory}')
    with manifest_path.open(encoding='utf-8') as stream:
        manifest = json.load(stream, object_pairs_hook=_unique_pairs)
    required = {'schema_version', 'source_scene', 'bundle_names', 'entries'}
    if not isinstance(manifest, dict) or set(manifest) != required:
        raise ValueError('Invalid checkpoint manifest schema')
    if (type(manifest['schema_version']) is not int or manifest['schema_version'] != 1
            or manifest['source_scene'] != os.path.normcase(str(scene))):
        raise ValueError('Checkpoint version/source scene mismatch')
    names = manifest['bundle_names']
    allowed = {p.name for p in _candidates(scene)}
    if (not isinstance(names, list) or not all(isinstance(n, str) for n in names)
            or len(set(names)) != len(names) or not set(names) <= allowed
            or scene.name not in names):
        raise ValueError('Invalid checkpoint bundle names')
    if set(p.name for p in directory.iterdir()) != set(names) | {MANIFEST}:
        raise ValueError('Unexpected checkpoint contents')
    for name in names:
        path = directory / name
        _safe_path(path)
        if (name == scene.name and not path.is_file()) or (name != scene.name and not path.is_dir()):
            raise ValueError(f'Invalid checkpoint member type: {name}')
    entries = _inventory(directory, names)
    if entries[scene.name]['size'] == 0 or entries != manifest['entries']:
        raise ValueError(f'Checkpoint hash/content mismatch or empty project: {directory}')
    if any(_is_lock(Path(name).name) for name in entries):
        raise ValueError('Checkpoint contains lock markers')
    return manifest


def _copy(base: Path, target: Path, names: list[str], *, ignore_locks=False) -> None:
    for name in names:
        source = base / name
        _safe_path(source)
        if source.is_dir():
            ignore = (lambda _d, children: [n for n in children if _is_lock(n)]) if ignore_locks else None
            shutil.copytree(source, target / name, ignore=ignore)
        else:
            shutil.copy2(source, target / name)


def _cleanup(path: Path, parent: Path, logger) -> None:
    """Only remove an explicitly owned, contained directory after safe traversal."""
    try:
        if path.parent != parent or path == parent:
            raise ValueError(f'Cleanup outside expected parent: {path}')
        _safe_path(path)
        if path.exists():
            for directory, dirs, files in os.walk(path, followlinks=False):
                for name in dirs + files:
                    _safe_path(Path(directory) / name)
            shutil.rmtree(path)
    except (OSError, ValueError) as exc:
        logger.warning('Retained directory %s: %s', path, exc)


def checkpoint_scene(scene_path: str, checkpoints_dir: str, tag: str, logger) -> str:
    scene, root, dest = _paths(scene_path, checkpoints_dir, tag)
    if not scene.is_file() or scene.stat().st_size == 0:
        raise ValueError(f'Cannot checkpoint missing/empty project: {scene}')
    names = _names(scene)
    entries = _inventory(scene.parent, names, ignore_locks=True)
    if dest.exists():
        _validate(dest, scene)
    root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.checkpoint-', dir=root))
    backup = None
    try:
        _copy(scene.parent, staging, names, ignore_locks=True)
        if (_names(scene) != names or _inventory(scene.parent, names, ignore_locks=True) != entries
                or _inventory(staging, names) != entries):
            raise ValueError('Scene changed or checkpoint copy differs; previous snapshot retained')
        manifest = {'schema_version': 1, 'source_scene': os.path.normcase(str(scene)),
                    'bundle_names': names, 'entries': entries}
        (staging / MANIFEST).write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        _validate(staging, scene)
        if dest.exists():
            backup = Path(tempfile.mkdtemp(prefix='.checkpoint-recovery-', dir=root))
            os.replace(dest, backup / tag)
        try:
            os.replace(staging, dest)
        except OSError as exc:
            if backup is not None:
                try:
                    os.replace(backup / tag, dest)
                except OSError as rollback:
                    raise RuntimeError(f'Checkpoint publish/rollback failed; previous snapshot retained at '
                                       f'{backup / tag}: {rollback}') from exc
            raise
        if backup is not None:
            _cleanup(backup, root, logger)
        logger.info('checkpoint "%s" -> %s', tag, dest)
        return str(dest)
    finally:
        _cleanup(staging, root, logger)


def restore_scene(scene_path: str, checkpoints_dir: str, tag: str, logger) -> None:
    scene, _, checkpoint = _paths(scene_path, checkpoints_dir, tag)
    manifest = _validate(checkpoint, scene)
    _no_locks(scene)
    current = _names(scene)
    current_entries = _inventory(scene.parent, current)
    needed = sum(e.get('size', 0) for e in manifest['entries'].values())
    try:
        free = shutil.disk_usage(scene.parent).free
    except OSError as exc:
        raise RuntimeError('REFUSING TO ROLL BACK: cannot establish free space') from exc
    if free < needed:
        raise RuntimeError(f'REFUSING TO ROLL BACK: need {needed} bytes, have {free}; '
                           f'live scene unchanged; snapshot: {checkpoint}')
    staging = Path(tempfile.mkdtemp(prefix='.scene-restore-', dir=scene.parent))
    try:
        _copy(checkpoint, staging, manifest['bundle_names'])
        if _inventory(staging, manifest['bundle_names']) != manifest['entries']:
            raise ValueError('Staged restore differs from checkpoint')
        _validate(checkpoint, scene)
        _no_locks(scene)
        if _names(scene) != current or _inventory(scene.parent, current) != current_entries:
            raise ValueError('Live scene changed during restore staging')
    except (OSError, ValueError, RuntimeError) as exc:
        _cleanup(staging, scene.parent, logger)
        raise RuntimeError(f'ROLLBACK INCOMPLETE: staging refused ({exc}); live scene unchanged. '
                           f'Checkpoint {checkpoint}; retry-safe after resolving the cause.') from exc
    backup = Path(tempfile.mkdtemp(prefix='.scene-recovery-', dir=scene.parent))
    moved, installed = [], []
    try:
        for name in current:
            os.replace(scene.parent / name, backup / name)
            moved.append(name)
        for name in manifest['bundle_names']:
            os.replace(staging / name, scene.parent / name)
            installed.append(name)
        _no_locks(scene)
        if _inventory(scene.parent, manifest['bundle_names']) != manifest['entries']:
            raise ValueError('Committed restore differs from checkpoint')
    except (OSError, ValueError, RuntimeError) as exc:
        failures = []
        for name in reversed(installed):
            try:
                os.replace(scene.parent / name, staging / name)
            except OSError as failure:
                failures.append(str(failure))
        for name in moved:
            try:
                if os.path.lexists(scene.parent / name):
                    raise OSError(f'Refusing to overwrite occupied recovery target: {name}')
                os.replace(backup / name, scene.parent / name)
            except OSError as failure:
                failures.append(str(failure))
        if not failures:
            _cleanup(backup, scene.parent, logger)
            _cleanup(staging, scene.parent, logger)
        raise RuntimeError(f'ROLLBACK INCOMPLETE: {exc}. '
                           + (f'Original members retained in {backup} or their live paths; '
                              f'recovery failures: {failures}. Staged files: {staging}. '
                              if failures else 'Original live bundle restored; ')
                           + f'checkpoint remains at {checkpoint}.') from exc
    _cleanup(backup, scene.parent, logger)
    _cleanup(staging, scene.parent, logger)
    logger.info('rolled back scene from checkpoint "%s"', tag)


def prune_checkpoints(checkpoints_dir: str, keep: set[str], logger) -> None:
    """Prune only validated checkpoints; retain unknown and recovery directories."""
    root = Path(os.path.abspath(checkpoints_dir))
    _safe_path(root)
    if not root.is_dir():
        return
    for path in root.iterdir():
        if path.name in keep or path.name.startswith('.'):
            continue
        try:
            _tag(path.name)
            _safe_path(path / MANIFEST)
            with (path / MANIFEST).open(encoding='utf-8') as stream:
                manifest = json.load(stream, object_pairs_hook=_unique_pairs)
            scene, _, _ = _paths(manifest['source_scene'], str(root), path.name)
            _validate(path, scene)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            logger.warning('Retained unvalidated checkpoint %s: %s', path, exc)
            continue
        _cleanup(path, root, logger)
