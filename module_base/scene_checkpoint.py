#!/usr/bin/env python3
"""Scene checkpoint / rollback by project-bundle file copy.

Lifted verbatim from grow_zone.py (2026-07-24) so the cross-zone merge
driver shares the SAME battle-tested restore path instead of forking it
("checkpoint/rollback validated in anger", FINDINGS 2026-07-24).
grow_zone.py re-exports these names; both drivers must keep importing
from here (single implementation, hard-rule spirit of CLAUDE.md #1).

Design (owner-mandated): a checkpoint is a plain file copy of the
.rsproj plus its companion data folder. Deliberately NOT an
export/fix/reimport round trip: reimported components do not contain
never-registered orphan images (silent drop, owner-confirmed
2026-07-23), and a relocated .rsalign import hangs the instance
(hard rule 7). The bundle copy avoids both hazards.
"""
from __future__ import annotations

import os
import shutil


def scene_bundle(scene_path: str) -> list[str]:
    """The .rsproj plus its companion data folder. A RealityScan save
    produces a sibling directory named exactly after the project stem
    (e.g. zone_1/ next to zone_1.rsproj) holding the bulky state as flat
    .dat blobs (sfmN.dat, appConfig0.dat, controlpoints0.dat, ...) -
    verified on D:/na156_h2023/aligned_components 2026-07-23. The extra
    candidates are defensive, in case a future build renames the folder."""
    stem = os.path.splitext(scene_path)[0]
    candidates = [scene_path, stem, stem + '.Data', scene_path + '.data']
    return [p for p in candidates if os.path.exists(p)]


def _tree_size(path: str) -> int:
    """Bytes under a file or directory (best effort)."""
    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
    return total


def checkpoint_scene(scene_path: str, checkpoints_dir: str, tag: str,
                     logger) -> str:
    dest = os.path.join(checkpoints_dir, tag)
    # Copy to <dest>.partial and swap only once the copy COMPLETES: the
    # previous version rmtree'd an existing same-tag checkpoint first, so
    # an interrupted re-checkpoint under a reused tag destroyed the last
    # good snapshot (audit 2026-08-07). Tag uniqueness is a caller
    # contract (grow_zone's tags are unique per pass) - this makes the
    # function safe even when a caller breaks it.
    staging = dest + '.partial'
    if os.path.isdir(staging):
        shutil.rmtree(staging)
    os.makedirs(staging)
    for src in scene_bundle(scene_path):
        target = os.path.join(staging, os.path.basename(src))
        if os.path.isdir(src):
            shutil.copytree(src, target,
                                ignore=shutil.ignore_patterns(
                                    '.lock', '*.lock'))
        else:
            shutil.copy2(src, target)
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    os.replace(staging, dest)
    logger.info('checkpoint "%s" -> %s', tag, dest)
    return dest


def restore_scene(scene_path: str, checkpoints_dir: str, tag: str, logger) -> None:
    """Rollback = restore the pre-pass scene snapshot to the SAME path.

    The live bundle must be removed before the copy so stale sidecar data
    cannot mix with the restored snapshot - which means there is a window
    where the scene path holds NOTHING. Two guards around it
    (audit 2026-08-07): a free-space precheck before the delete (bundles
    are multi-GB and this path had no disk floor at all, while run_models
    has MIN_FREE_GB=50), and a named RuntimeError if the copy dies, because
    grow_zone calls this in four places with no try/except and the run
    otherwise ended with an empty scene path and no message saying the
    intact copy is still in checkpoints/<tag>. Re-running the same restore
    finishes the job; it is retry-safe.
    """
    src_dir = os.path.join(checkpoints_dir, tag)
    if not os.path.isdir(src_dir):
        raise FileNotFoundError(f'checkpoint "{tag}" not found in {checkpoints_dir}')
    scene_dir = os.path.dirname(os.path.normpath(scene_path)) or '.'
    needed = _tree_size(src_dir)
    try:
        free = shutil.disk_usage(scene_dir).free
    except OSError:
        free = None
    if free is not None and free < needed:
        raise RuntimeError(
            f'REFUSING TO ROLL BACK: checkpoint "{tag}" needs '
            f'{needed / 1024**3:.1f} GB but only {free / 1024**3:.1f} GB is '
            f'free on {scene_dir}. The rollback deletes the live scene '
            'before copying, so starting it now would leave the scene path '
            f'empty. Free space, then re-run - the snapshot is intact in '
            f'{src_dir}.')
    # Remove the rejected bundle first so stale sidecar data can never
    # mix with the restored snapshot. LOCK-TOLERANT (2026-08-12): a LIVE
    # instance holds <companion>\.lock open; rmtree dies on it (WinError
    # 32) - and because dotfiles sort first it dies BEFORE touching any
    # scene data, leaving the bundle intact but the rollback failed.
    # Locks are runtime artifacts, never scene data: skip them during
    # the clear (checkpoints exclude them on the way in already); any
    # OTHER locked file still fails loudly.
    def _clear_tree(root):
        for r, dirs, files in os.walk(root, topdown=False):
            for f in files:
                if f.endswith('.lock'):
                    continue
                os.remove(os.path.join(r, f))
            for d in dirs:
                try:
                    os.rmdir(os.path.join(r, d))
                except OSError:
                    pass  # still holds a .lock - fine
    for cur in scene_bundle(scene_path):
        if os.path.isdir(cur):
            _clear_tree(cur)
        elif os.path.isfile(cur):
            os.remove(cur)
    try:
        for name in os.listdir(src_dir):
            src = os.path.join(src_dir, name)
            target = os.path.join(scene_dir, name)
            if os.path.isdir(src):
                # dirs_exist_ok: the lock-tolerant clear leaves the live
                # companion dir in place (it still holds the .lock).
                shutil.copytree(src, target,
                                ignore=shutil.ignore_patterns(
                                    '.lock', '*.lock'),
                                dirs_exist_ok=True)
            else:
                shutil.copy2(src, target)
    except OSError as exc:
        raise RuntimeError(
            f'ROLLBACK INCOMPLETE: {scene_path} is now partial or absent '
            f'({exc}). The INTACT snapshot is {src_dir} - re-run the same '
            'restore to finish it (it is retry-safe). Do not start another '
            'workflow against this scene first.') from exc
    logger.info('rolled back scene from checkpoint "%s"', tag)


def prune_checkpoints(checkpoints_dir: str, keep: set[str], logger) -> None:
    """Scene bundles are large (multi-GB); keep only the initial
    checkpoint and the most recent one."""
    if not os.path.isdir(checkpoints_dir):
        return
    for name in os.listdir(checkpoints_dir):
        if name in keep:
            continue
        path = os.path.join(checkpoints_dir, name)
        if os.path.isdir(path):
            try:
                shutil.rmtree(path)
                logger.info('pruned checkpoint "%s"', name)
            except OSError as exc:
                logger.warning('could not prune checkpoint %s: %s', name, exc)
