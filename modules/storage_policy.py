"""Volume-aware capacity gates and read-only temporary-file cleanup proposals.

Controller API: assess_storage(demands) returns alerts; require_start_space(demands)
raises StorageBlocked before work starts. During a run pass REMAINING byte growth
as demands, not the original total again. These functions never write/delete.
Demand values use GiB (bytes / 1024**3). The approved reserve defaults to 50 GiB.
For the current project the controller supplies F:/NA171 and
F:/NA171/proc/tmp/cache; no campaign paths or historical free-space values are
used as defaults or inferred from a manifest.

Cleanup manifest schema 1: project_id, files [{path (root-relative proc/tmp file),
kind: temporary, owner_id, producer_stage, attempt_id, size_bytes, sha256}].
stage_evidence maps producer_stage to {attempt_id, saved: True, verified: True}.
Those booleans are evidence supplied by the checkpoint controller, not inferred
from an exit code. active_owner_ids must be an explicit, current snapshot; None
means unknown. No deletion API exists here. A reviewed plan is not permission to
delete and must be revalidated against ownership/checkpoints before later use.
"""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
import hashlib
import math
import ntpath
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import stat

from .run_charter import _contains

GIB = 1024 ** 3
DEFAULT_RESERVE_GIB = 50.0
DEFAULT_ALERT_MARGIN_GIB = 10.0


class StoragePolicyError(ValueError):
    """Invalid demand, manifest or ownership evidence."""


class StorageBlocked(RuntimeError):
    """Capacity cannot support a start; report contains actionable alerts."""

    def __init__(self, report: dict):
        self.report = report
        super().__init__('; '.join(alert['message'] for alert in report['alerts']
                                  if alert['level'] == 'block'))


@dataclass(frozen=True)
class StorageDemand:
    """Additional allocation in GiB; use separate output and cache demands."""

    path: str | Path
    delta_gib: float
    label: str


def _bytes(gib, field: str) -> int:
    if isinstance(gib, bool) or not isinstance(gib, (int, float)):
        raise StoragePolicyError(f'{field} must be a finite nonnegative GiB number')
    try:
        valid = math.isfinite(gib) and gib >= 0 and math.isfinite(gib * GIB)
    except OverflowError:
        valid = False
    if not valid:
        raise StoragePolicyError(f'{field} must be a finite nonnegative GiB number')
    return math.ceil(gib * GIB)


def resolve_volume(path: str | Path) -> dict:
    """Resolve mounted/junction paths to a volume identity, never a drive letter.

    Uses the nearest existing directory for destinations not created yet. Windows
    volume GUIDs identify the capacity pool, not the physical disk containing it:
    two partitions on one disk have separate budgets. Unsupported network volume
    identity fails closed rather than guessing that two share names are separate.
    """
    target = Path(path)
    if not target.is_absolute():
        raise StoragePolicyError(f'Absolute storage path required: {path}')
    target = target.resolve()
    anchor = target
    while not anchor.exists() and anchor.parent != anchor:
        anchor = anchor.parent
    if not anchor.exists():
        raise StoragePolicyError(f'No mounted ancestor for {path}')
    if not anchor.is_dir():
        anchor = anchor.parent
    if os.name == 'nt':
        from ctypes import wintypes

        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.GetVolumePathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        api.GetVolumePathNameW.restype = wintypes.BOOL
        api.GetVolumeNameForVolumeMountPointW.argtypes = [
            wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        api.GetVolumeNameForVolumeMountPointW.restype = wintypes.BOOL
        mount, identity = ctypes.create_unicode_buffer(32768), ctypes.create_unicode_buffer(1024)
        if not api.GetVolumePathNameW(str(anchor), mount, len(mount)):
            raise StoragePolicyError(f'Cannot resolve volume mount for {path}: {ctypes.get_last_error()}')
        if not api.GetVolumeNameForVolumeMountPointW(mount.value, identity, len(identity)):
            raise StoragePolicyError(f'Cannot resolve volume identity for {path}: {ctypes.get_last_error()}')
        volume_id = identity.value.casefold()
    else:
        volume_id = f'device:{anchor.stat().st_dev}'
    return {'volume_id': volume_id, 'anchor': str(anchor), 'path': str(target)}


def assess_storage(demands: list[StorageDemand], *, reserve_gib: float = DEFAULT_RESERVE_GIB,
                   alert_margin_gib: float = DEFAULT_ALERT_MARGIN_GIB) -> dict:
    """Sum all growth and charge one reserve per resolved volume.

    Free space is sampled exactly once per volume per call. Unknown volume/free
    space blocks. Runtime callers consume alerts; this function never pauses,
    kills a worker or deletes a file. Missing estimates must not become zero.
    """
    reserve = _bytes(reserve_gib, 'reserve_gib')
    margin = _bytes(alert_margin_gib, 'alert_margin_gib')
    if not demands:
        raise StoragePolicyError('At least one storage demand is required')
    groups, alerts = {}, []
    labels = set()
    for demand in demands:
        if not isinstance(demand, StorageDemand):
            raise StoragePolicyError('demands must contain StorageDemand values')
        delta = _bytes(demand.delta_gib, demand.label)
        if not isinstance(demand.label, str) or not demand.label.strip() or demand.label in labels:
            raise StoragePolicyError('Storage demand labels must be nonempty and unique')
        labels.add(demand.label)
        try:
            location = resolve_volume(demand.path)
        except (OSError, RuntimeError, StoragePolicyError) as exc:
            alerts.append({'level': 'block', 'volume_id': None,
                           'message': f'{demand.label}: cannot measure storage at {demand.path}: {exc}'})
            continue
        key = location['volume_id']
        group = groups.setdefault(key, {'volume_id': key, 'anchor': location['anchor'],
                                       'demands': [], 'delta_bytes': 0, 'reserve_bytes': reserve})
        group['demands'].append({'path': location['path'], 'label': demand.label, 'delta_bytes': delta})
        group['delta_bytes'] += delta
    for key, group in groups.items():
        required = group['delta_bytes'] + reserve
        group.update(required_bytes=required, free_bytes=None, headroom_bytes=None, status='block')
        try:
            free = shutil.disk_usage(group['anchor']).free
            if not isinstance(free, int) or free < 0:
                raise StoragePolicyError('Invalid free-space measurement')
        except (OSError, StoragePolicyError) as exc:
            alerts.append({'level': 'block', 'volume_id': key,
                           'message': f'Cannot measure free space on {group["anchor"]}: {exc}'})
            continue
        headroom = free - required
        status = 'block' if headroom < 0 else ('warning' if headroom < margin else 'ok')
        group.update(free_bytes=free, headroom_bytes=headroom, status=status)
        group['message'] = (
            f'{free / GIB:.1f} GiB free on {group["anchor"]}; '
            f'{group["delta_bytes"] / GIB:.1f} GiB combined '
            f'{" + ".join(d["label"] for d in group["demands"])} growth + '
            f'{reserve / GIB:.1f} GiB reserve; {headroom / GIB:.1f} GiB headroom')
        if status != 'ok':
            alerts.append({'level': status, 'volume_id': key, 'message': group['message']})
    return {'schema': 1, 'can_start': not any(a['level'] == 'block' for a in alerts),
            'volumes': list(groups.values()), 'alerts': alerts, 'automatic_deletion': False}


def require_start_space(demands: list[StorageDemand], *, reserve_gib=DEFAULT_RESERVE_GIB,
                        alert_margin_gib=DEFAULT_ALERT_MARGIN_GIB) -> dict:
    """Fresh blocking start gate; never trusts a prior report's free-space sample."""
    report = assess_storage(demands, reserve_gib=reserve_gib, alert_margin_gib=alert_margin_gib)
    if not report['can_start']:
        raise StorageBlocked(report)
    return report


def _temp_path(root: Path, relative: str, protected: list[Path]) -> Path:
    if not isinstance(relative, str) or not relative:
        raise StoragePolicyError('Manifest path must be a nonempty relative string')
    parts = relative.split('/')
    if (PureWindowsPath(relative).anchor or '\\' in relative or len(parts) < 3
            or [p.casefold() for p in parts[:2]] != ['proc', 'tmp']
            or any(p in ('', '.', '..') or p.endswith((' ', '.')) or ntpath.isreserved(p)
                   or any(c in p for c in '<>:"|?*') or any(ord(c) < 32 for c in p) for p in parts)):
        raise StoragePolicyError('Only normalized manifest-owned proc/tmp files can be proposed')
    if any(p.casefold() in {'source', 'sources', 'raw', 'final', 'deliverables', 'exports'} for p in parts):
        raise StoragePolicyError('Source/raw/deliverable paths cannot be cleanup targets')
    target = root.joinpath(*parts)
    for ancestor in (target, *target.parents):
        if ancestor.is_symlink() or ancestor.is_junction():
            raise StoragePolicyError('Redirected cleanup paths are forbidden')
    resolved = target.resolve()
    if not _contains(root / 'proc' / 'tmp', resolved):
        raise StoragePolicyError('Cleanup path escaped proc/tmp')
    if any(_contains(p, resolved) or _contains(resolved, p) for p in protected):
        raise StoragePolicyError('Cleanup target overlaps a protected/source/deliverable path')
    metadata = resolved.stat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise StoragePolicyError('Cleanup targets must be regular files without hardlinks')
    return resolved


def plan_cleanup(project_root: str | Path, manifest: dict, *, project_id: str,
                 stage_evidence: dict, active_owner_ids: set[str] | None,
                 protected_paths=()) -> dict:
    """Read-only plan of exact owned temporary files; never glob or delete.

    Any active owner blocks the whole plan, including possible consumers from
    another stage. Only explicit True saved/verified evidence for the producing
    attempt qualifies. Plans are snapshots, not executable deletion manifests.
    """
    root = Path(project_root)
    if not root.is_absolute() or root.parent == root:
        raise StoragePolicyError('Cleanup requires an absolute project directory, not a volume root')
    if (not isinstance(manifest, dict) or type(manifest.get('schema')) is not int
            or manifest['schema'] != 1 or not project_id or manifest.get('project_id') != project_id
            or not isinstance(manifest.get('files'), list)):
        raise StoragePolicyError('Invalid cleanup manifest schema/project ownership')
    if not isinstance(stage_evidence, dict):
        raise StoragePolicyError('Stage checkpoint evidence is required')
    if active_owner_ids is not None and (not isinstance(active_owner_ids, (set, frozenset))
                                        or any(not isinstance(x, str) or not x for x in active_owner_ids)):
        raise StoragePolicyError('active_owner_ids must be a set of owner IDs or None (unknown)')
    protected = []
    for value in protected_paths:
        path = Path(value)
        if not path.is_absolute():
            raise StoragePolicyError('Protected paths must be absolute')
        protected.append(path.resolve())
    plan = {'schema': 1, 'project_id': project_id, 'project_root': str(root),
            'candidates': [], 'refused': [], 'reclaimable_bytes': 0,
            'requires_explicit_review': True, 'automatic_deletion': False}
    seen = set()
    # Ambiguous ownership for duplicate paths invalidates the manifest, instead
    # of accepting the first record and leaving a misleading partial proposal.
    for entry in manifest['files']:
        if not isinstance(entry, dict) or not isinstance(entry.get('path'), str):
            raise StoragePolicyError('Each cleanup entry must have a relative path')
        key = entry['path'].casefold()
        if key in seen:
            raise StoragePolicyError(f'Duplicate cleanup path: {entry["path"]}')
        seen.add(key)
    for entry in manifest['files']:
        try:
            if active_owner_ids is None or active_owner_ids:
                raise StoragePolicyError('Active ownership is unknown or an owner is still active')
            for key in ('owner_id', 'producer_stage', 'attempt_id'):
                if not isinstance(entry.get(key), str) or not entry[key].strip():
                    raise StoragePolicyError(f'Missing manifest ownership field: {key}')
            if entry.get('kind') != 'temporary':
                raise StoragePolicyError('Manifest does not classify this file as temporary')
            evidence = stage_evidence.get(entry['producer_stage'])
            if (not isinstance(evidence, dict) or evidence.get('saved') is not True
                    or evidence.get('verified') is not True
                    or evidence.get('active') is True
                    or evidence.get('attempt_id') != entry['attempt_id']):
                raise StoragePolicyError('Producing attempt lacks matching saved and verified evidence')
            if (type(entry.get('size_bytes')) is not int or entry['size_bytes'] < 0
                    or not isinstance(entry.get('sha256'), str)
                    or not re.fullmatch('[0-9a-f]{64}', entry['sha256'])):
                raise StoragePolicyError('Manifest must record size_bytes and SHA-256')
            target = _temp_path(root, entry['path'], protected)
            with target.open('rb') as stream:
                before = os.fstat(stream.fileno())
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                after = os.fstat(stream.fileno())
            current = _temp_path(root, entry['path'], protected).stat()
            identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_nlink)
            if (identity(before) != identity(after) or identity(after) != identity(current)
                    or after.st_size != entry['size_bytes'] or digest != entry['sha256']):
                raise StoragePolicyError('Owned file changed since its manifest fingerprint')
            plan['candidates'].append({**entry, 'absolute_path': str(target),
                                       'device': current.st_dev, 'file_id': current.st_ino,
                                       'mtime_ns': current.st_mtime_ns})
            plan['reclaimable_bytes'] += current.st_size
        except (OSError, RuntimeError, StoragePolicyError) as exc:
            plan['refused'].append({'path': entry['path'], 'reason': str(exc)})
    return plan
