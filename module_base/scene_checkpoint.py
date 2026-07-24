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


def checkpoint_scene(scene_path: str, checkpoints_dir: str, tag: str,
                     logger) -> str:
    dest = os.path.join(checkpoints_dir, tag)
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    for src in scene_bundle(scene_path):
        target = os.path.join(dest, os.path.basename(src))
        if os.path.isdir(src):
            shutil.copytree(src, target)
        else:
            shutil.copy2(src, target)
    logger.info('checkpoint "%s" -> %s', tag, dest)
    return dest


def restore_scene(scene_path: str, checkpoints_dir: str, tag: str, logger) -> None:
    """Rollback = restore the pre-pass scene snapshot to the SAME path."""
    src_dir = os.path.join(checkpoints_dir, tag)
    if not os.path.isdir(src_dir):
        raise FileNotFoundError(f'checkpoint "{tag}" not found in {checkpoints_dir}')
    # Remove the rejected bundle first so stale sidecar data can never
    # mix with the restored snapshot.
    for cur in scene_bundle(scene_path):
        if os.path.isdir(cur):
            shutil.rmtree(cur)
        else:
            os.remove(cur)
    scene_dir = os.path.dirname(os.path.normpath(scene_path))
    for name in os.listdir(src_dir):
        src = os.path.join(src_dir, name)
        target = os.path.join(scene_dir, name)
        if os.path.isdir(src):
            shutil.copytree(src, target)
        else:
            shutil.copy2(src, target)
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
