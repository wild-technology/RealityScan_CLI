"""Post-batch temporal-mask integration; no planner, launcher or source writes.

The controller owns the project operation lease and review approval. This helper
owns immutable generation/decision manifests and receipts for exact mask copies.
All public operations re-read current batch evidence. Generated masks are never
part of the batch fingerprint, but are checked separately before alignment.
Geometry with embedded alpha or transparency is unsupported, including opaque
alpha channels. Supply opaque inputs and rebatch; this helper never flattens or
rewrites images. Skip means no external or embedded masks, not merely no copies.
"""
from __future__ import annotations

from dataclasses import asdict
import csv
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from PIL import Image

from . import camera_registry, image_exts, temporal_occlusion as engine
from .project_reviews import ReviewStore, digest, write_json
from .source_inventory import approval_token, file_hash
from .storage_policy import StorageDemand, require_start_space, GIB


VERSION = 'project-occlusion-1'
ARTIFACT_ROOT = 'proc/masks/occlusion'


def _cancel(cancelled):
    if cancelled and cancelled():
        raise InterruptedError('Project occlusion operation cancelled')


def _path(project, value, *, file=False):
    original = Path(value)
    if not original.is_absolute():
        original = project.root / original
    for ancestor in (original, *original.parents):
        if ancestor.is_symlink() or ancestor.is_junction():
            raise ValueError('Occlusion paths must not be redirected')
    path = project.resolve_path(value)
    if file and (not path.is_file() or path.stat().st_nlink != 1):
        raise ValueError(f'Occlusion evidence must be a regular, unaliased file: {path}')
    return path


def _relative(project, path):
    return _path(project, path).relative_to(project.root).as_posix()


def _json(project, path):
    value = json.loads(_path(project, path, file=True).read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Occlusion evidence must be a JSON object')
    return value


def _files(project, root):
    root = _path(project, root)
    result = []
    for directory, dirs, files in os.walk(root):
        for name in dirs:
            _path(project, Path(directory) / name)
        for name in files:
            result.append(_path(project, Path(directory) / name, file=True))
    return sorted(result)


def _is_mask(path):
    return '.mask.' in path.name.casefold() or any(part.casefold() in ('.mask', '_mask') for part in path.parts)


def _record(project, path, cancelled=None):
    path = _path(project, path, file=True)
    return dict(path=_relative(project, path), sha256=file_hash(path, cancelled=cancelled),
                bytes=path.stat().st_size)


def _check_record(project, record, cancelled=None):
    actual = _record(project, record['path'], cancelled)
    if actual != {key: record[key] for key in actual}:
        raise ValueError('Occlusion artifact content changed: ' + record['path'])
    return _path(project, record['path'], file=True)


def _owner(project):
    value = _json(project, '.rovscan-owner.json')
    if value.get('schema') != 1 or value.get('project_id') != project.project_id:
        raise ValueError('Project occlusion requires the existing project ownership record')


def _reserve(project, size):
    operating = project.to_dict()['settings'].get('operating', {}).get('values', {})
    if 'reserve_gib' not in operating:
        raise ValueError('Explicit operating reserve_gib is required')
    return require_start_space([StorageDemand(_path(project, ARTIFACT_ROOT), size / GIB, 'occlusion masks')],
                               reserve_gib=operating['reserve_gib'])


def _extent(path, item):
    with Image.open(path) as image:
        # Native image alpha can itself become a mask, even with no sidecars.
        # PNG tRNS also carries transparency without an explicit alpha band.
        if any(band.casefold() == 'a' for band in image.getbands()) or 'transparency' in image.info:
            raise ValueError('Embedded alpha/transparency masks are unsupported: ' + str(path)
                             + '. Supply opaque geometry inputs and rebatch before Apply or Skip; '
                               'images are never modified or flattened here.')
        exif = image.getexif()
        width, height = image.size
        if (getattr(image, 'n_frames', 1) != 1 or exif.get(274, 1) != 1
                or width * height > engine.MAX_PIXELS or min(width, height) < 32):
            raise ValueError('Unsupported/non-normalized batch frame extent')
        if camera_registry.FAMILY_CAMERA.get(item.family) != item.camera:
            raise ValueError('Batch camera/family is not a registered optical identity')
        # Bind physical identity and observed image framing, not process-local
        # calibration/mount/accuracy priors. Project science invalidation owns
        # those settings; loading them must not change unchanged image identity.
        extent = digest(dict(camera=item.camera, family=item.family,
                             width=width, height=height, orientation=1,
                             acquisition_domain=Path(item.relative_path).parent.as_posix(),
                             sensor_tags={str(tag): str(exif.get(tag, '')) for tag in
                                          (271, 272, 42033, 42036, 50719, 50720, 50829)}))
    return width, height, extent


def context(project, *, cancelled=None, progress=None):
    """Fresh opaque-geometry census, independent of generated mask sidecars.

    Embedded alpha/transparency is rejected for every image, including Skip.
    """
    _cancel(cancelled)
    _owner(project)
    if project.to_dict()['stages']['batch']['state'] != 'succeeded':
        raise ValueError('Complete the current native batch stage before occlusion review')
    store = ReviewStore(project)
    workflow = store.read('workflow')
    if workflow.get('invalidated_by') or digest(workflow['payload']) != workflow.get('assessment_hash'):
        raise ValueError('Workflow review is stale or malformed')
    workflow = workflow['payload']
    items = store.selection()
    selection_hash = approval_token(items)
    if workflow['selection_hash'] != selection_hash:
        raise ValueError('Workflow selection changed; rebatch before occlusion review')
    root = _path(project, workflow['root'])
    if not root.is_relative_to(project.root / 'proc' / 'workflows'):
        raise ValueError('Occlusion requires an owned proc/workflows batch')
    batch = _path(project, root / 'batched_images_by_zone')
    marker_path = batch / 'batch_inputs.json'
    marker = _json(project, marker_path)
    if marker.get('status') != 'complete':
        raise ValueError('Batch census is incomplete; finish/rebatch first')
    if marker.get('params', {}).get('batch_zone_layout', 'copy') != 'copy':
        raise ValueError('Post-batch masking requires copy layout; rebatch with batch_zone_layout=copy')
    selection = _json(project, workflow['selection_manifest'])
    if selection.get('project_id') != project.project_id or selection.get('selection_hash') != selection_hash:
        raise ValueError('Selection manifest belongs to a different project/selection')
    if selection.get('masks'):
        raise ValueError('Retire source masks and rebatch before optional generated masks')
    from .image_batcher.batch_directory import validate_selection_manifest
    binding = validate_selection_manifest(_path(project, workflow['selection_manifest'], file=True),
                                          selection['images_root'], selection['flight_log'], cancelled=cancelled)
    if marker.get('selection') != binding:
        raise ValueError('Batch fingerprint does not bind the current selected inputs')
    expected = {Path(item.path).name.casefold(): item for item in items
                if item.kind == 'image' and item.included and not item.duplicate_of}
    if len(expected) != sum(item.kind == 'image' and item.included and not item.duplicate_of for item in items):
        raise ValueError('Ambiguous retained image basenames')
    selected_images = {Path(row['path']).name.casefold(): row for row in selection['images']}
    zones = sorted(path for path in batch.iterdir() if path.is_dir() and path.name.startswith('zone_'))
    if not zones:
        raise ValueError('Completed batch contains no zones')
    for path in _files(project, batch):
        if (image_exts.is_geometry_image(path) or _is_mask(path)) and not any(path.is_relative_to(zone) for zone in zones):
            raise ValueError('Geometry/mask layer is outside the recorded zone layout')
    copies, frames, evidence, masks, seen, extents, images = [], {}, [], [], set(), {}, {}
    for zone in zones:
        zone_files = _files(project, zone)
        zone_images = [p for p in zone_files if image_exts.is_geometry_image(p)]
        if not zone_images or any(p.suffix == '.imagelist' for p in zone_files):
            raise ValueError('Every copy-layout zone must contain geometry images')
        members = set()
        for path in zone_images:
            _cancel(cancelled)
            item = expected.get(path.name.casefold())
            if item is None or path.parent.name != item.camera or path.parent.parent != zone:
                raise ValueError('Unknown or misplaced batch image: ' + str(path))
            record = _record(project, path, cancelled)
            if record['sha256'] != item.sha256:
                raise ValueError('Batch image differs from approved selected content: ' + str(path))
            header_key = (record['sha256'], item.camera, item.family, Path(item.relative_path).parent.as_posix())
            if header_key not in extents:
                extents[header_key] = _extent(path, item)
            width, height, extent = extents[header_key]
            frame = engine.TemporalFrame(str(path), item.sha256, item.camera, item.family,
                                         item.timestamp_utc, extent, width, height)
            image_id = engine.canonical_image_id(frame)
            if image_id in frames and frames[image_id]['timestamp_utc'] != frame.timestamp_utc:
                raise ValueError('Duplicate camera content has conflicting timestamps')
            frames.setdefault(image_id, asdict(frame))
            selected_image = selected_images[path.name.casefold()]
            images[image_id] = dict(path=_relative(project, selected_image['path']), sha256=selected_image['sha256'])
            copies.append(dict(record, image_id=image_id, zone=zone.name))
            evidence.append(record)
            members.add(path.name.casefold())
            seen.add(path.name.casefold())
            if progress:
                progress('census', len(copies), 0, str(path))
        log_record = marker.get('zone_flight_logs', {}).get(zone.name)
        if not isinstance(log_record, dict):
            raise ValueError('Zone has no recorded flight-log fingerprint')
        log = _path(project, zone / log_record['file'], file=True)
        if log.parent != zone or file_hash(log, cancelled=cancelled) != log_record['sha256']:
            raise ValueError('Zone flight log changed')
        with log.open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.reader(stream, delimiter=';'))
        names = [Path(row[0].replace('\\', '/')).name.casefold() for row in rows[1:] if row]
        if len(names) != len(set(names)) or set(names) != members:
            raise ValueError('Zone geometry differs from its flight-log membership')
        for path in zone_files:
            if image_exts.is_geometry_image(path):
                continue
            if _is_mask(path):
                masks.append(_record(project, path, cancelled))
            elif path == log:
                evidence.append(_record(project, path, cancelled))
            elif path.suffix.casefold() in image_exts.ALL_IMAGE_EXTS:
                raise ValueError('Unknown geometry/layer file in batch: ' + str(path))
    if seen != set(expected) or set(marker.get('zone_flight_logs', {})) != {z.name for z in zones}:
        raise ValueError('Batch coverage or zone set differs from the retained selection')
    native_paths = {row['path'] + '.mask.png' for row in copies}
    if any(row['path'] not in native_paths for row in masks):
        raise ValueError('Unsupported/orphan mask layout; only exact image.ext.mask.png sidecars are supported')
    result = dict(schema=1, version=VERSION, project_id=project.project_id,
                  workflow_root=_relative(project, root), batch_root=_relative(project, batch),
                  selection_hash=selection_hash, batch_attempt_id=project.to_dict()['stages']['batch']['attempts'][-1]['id'],
                  extent_limit='Physical camera/family, dimensions, EXIF sensor/crop tags and source acquisition directory are bound; '
                               'missing crop metadata cannot prove equal physical framing. Review every proposal.',
                  batch_inputs=_record(project, marker_path, cancelled),
                  selection_manifest=_record(project, workflow['selection_manifest'], cancelled),
                  files=sorted(evidence, key=lambda row: row['path']),
                  frames=[dict(frame, image_id=key) for key, frame in sorted(frames.items())],
                  images=images,
                  copies=sorted(copies, key=lambda row: row['path']))
    return dict(result, batch_fingerprint=digest(result), existing_masks=masks)


def _fresh(project, supplied, cancelled=None, progress=None):
    live = context(project, cancelled=cancelled, progress=progress)
    if (not isinstance(supplied, dict) or supplied.get('project_id') != project.project_id
            or supplied.get('batch_fingerprint') != live['batch_fingerprint']):
        raise ValueError('Batch changed; regenerate/review occlusion masks')
    return live


def parameter_schema():
    """Expose the engine's single source of defaults, bounds and step sizes."""
    return engine.parameter_schema()


def _new_folder(project):
    folder = _path(project, ARTIFACT_ROOT + '/' + uuid4().hex)
    folder.mkdir(parents=True, exist_ok=False)
    return folder


def _mutation_guard(project):
    if any(project.to_dict()['stages'][stage]['state'] == 'running'
           for stage in ('align', 'merge', 'model', 'export')):
        raise ValueError('Do not change occlusion masks while a downstream stage is running')


def _immutable(project, path, value):
    path = _path(project, path)
    content = json.dumps(value, sort_keys=True, allow_nan=False, indent=2).encode('utf-8')
    with path.open('xb') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    return _record(project, path)


def generate(project, context, options=None, *, cancelled=None, progress=None):
    _mutation_guard(project)
    live = _fresh(project, context, cancelled, progress)
    config = engine.TemporalMaskConfig(**(options or {}))
    config.validate()
    frames = [engine.TemporalFrame(**{k: v for k, v in row.items() if k != 'image_id'}) for row in live['frames']]
    blocks = engine.plan_temporal_blocks(frames, block_seconds=config.block_seconds)
    _reserve(project, sum(b['width'] * b['height'] * 6 + 2**20 for b in blocks))
    _cancel(cancelled)
    folder, groups = _new_folder(project), []
    for block in blocks:
        _cancel(cancelled)
        members = [engine.TemporalFrame(**{k: v for k, v in row.items() if k != 'image_id'}) for row in block['members']]
        assessment = engine.assess_temporal_occlusion(members, source_root=_path(project, live['batch_root']),
            batch_id=block['block_id'], selection_hash=live['selection_hash'], config=config,
            cancelled=cancelled, progress=progress)
        preview = engine.write_temporal_preview(assessment, artifact_dir=folder / 'previews')
        groups.append(dict(group_id=block['block_id'], camera=block['camera'], family=block['family'],
            start_unix=block['start_unix'], block_seconds=block['block_seconds'],
            image_count=len(block['members']), sample_count=len(assessment['sampled_frames']),
            excluded_fraction=assessment['metrics']['candidate_fraction'], status=assessment['status'],
            blockers=assessment['blockers'], image_ids=assessment['image_ids'],
            assessment=_record(project, preview['assessment_path']),
            preview_records=[_record(project, preview[key]) for key in ('mask_preview_path', 'overlay_path')],
            previews=[dict(image_path=assessment['sampled_frames'][0]['path'], overlay_path=preview['overlay_path'])]))
    _fresh(project, live, cancelled)
    body = dict(schema=1, version=VERSION, project_id=project.project_id, decision='generated',
                batch_fingerprint=live['batch_fingerprint'], selection_hash=live['selection_hash'],
                parameters=asdict(config), parameter_schema=parameter_schema(), groups=groups)
    manifest = _immutable(project, folder / 'generation.json', body)
    return dict(body, generation_manifest=manifest['path'], generation_sha256=manifest['sha256'])


def _manifest(project, payload, kind):
    path = _path(project, payload[kind + '_manifest'], file=True)
    if not path.is_relative_to(_path(project, ARTIFACT_ROOT)):
        raise ValueError('Occlusion manifest is outside the owned artifact namespace')
    if file_hash(path) != payload[kind + '_sha256']:
        raise ValueError('Occlusion manifest hash changed')
    value = _json(project, path)
    if value.get('version') != VERSION or value.get('project_id') != project.project_id:
        raise ValueError('Occlusion manifest belongs to a different project/version')
    if any(payload.get(key) != expected for key, expected in value.items()):
        raise ValueError('Displayed/approved occlusion payload differs from its immutable manifest')
    return value


def _identity(path):
    stat = path.stat()
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_ctime_ns]


def _stable_identity(stat):
    # Neither ctime nor birth time is rename-stable: Windows can tunnel the old
    # destination's creation time on reapply. Use volume + persistent file ID.
    # A filesystem without a meaningful file ID cannot prove ownership.
    if not stat.st_ino:
        raise ValueError('Filesystem cannot prove mask file identity')
    return [stat.st_dev, stat.st_ino]


class _CopyJournal:
    """One fsynced intent before each rename; O(n) append-only ownership evidence."""

    def __init__(self, project, folder, batch_root):
        self.project, self.folder = project, folder
        self.stream = (folder / 'copies.jsonl').open('xb')
        self.previous = None
        try:
            self.append(dict(event='header', schema=1, version=VERSION,
                             project_id=project.project_id, batch_root=batch_root))
        except BaseException:
            self.close()
            raise

    def append(self, entry):
        entry = dict(entry, previous=self.previous)
        checksum = digest(entry)
        self.stream.write(json.dumps(dict(entry=entry, checksum=checksum),
                                     separators=(',', ':'), allow_nan=False).encode('utf-8') + b'\n')
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.previous = checksum

    def close(self):
        self.stream.close()


def _journal_records(project, path, wanted, cancelled):
    """Read only complete, chained records; a torn final append proves nothing.

    A prepared record owns a promoted target only when stable identity AND full
    content match. A filename or matching content alone never establishes it.
    """
    prepared, published, previous = {}, {}, None
    with _path(project, path, file=True).open('rb') as stream:
        for number, line in enumerate(stream):
            _cancel(cancelled)
            if not line.endswith(b'\n'):
                break
            try:
                wrapper = json.loads(line)
                entry = wrapper['entry']
                if entry['previous'] != previous or wrapper['checksum'] != digest(entry):
                    raise ValueError('Invalid ownership journal checksum/sequence')
                previous = wrapper['checksum']
                if number == 0:
                    batch = entry['batch_root'].replace('\\', '/').casefold().rstrip('/') + '/'
                    if not any(key.startswith(batch) for key in wanted):
                        return []
                    if (entry['event'] != 'header' or entry['schema'] != 1
                            or entry['version'] != VERSION or entry['project_id'] != project.project_id):
                        raise ValueError('Foreign occlusion ownership journal')
                    continue
                record = entry['record']
                key = record['path'].replace('\\', '/').casefold()
                if key not in wanted:
                    continue
                if entry['event'] == 'prepared':
                    if key in prepared:
                        raise ValueError('Duplicate prepared mask target')
                    temporary = _path(project, entry['temporary'])
                    if temporary.parent != path.parent or temporary.suffix != '.partial':
                        raise ValueError('Invalid prepared mask temporary path')
                    prepared[key] = entry
                elif entry['event'] == 'published':
                    intent = prepared.get(key)
                    if (intent is None or key in published
                            or any(record.get(k) != v for k, v in intent['record'].items())):
                        raise ValueError('Mask publication has no matching prepared intent')
                    published[key] = record
                else:
                    raise ValueError('Unknown ownership journal event')
            except (KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
                raise ValueError('Malformed occlusion ownership journal') from exc
    result = []
    for key, intent in prepared.items():
        record = intent['record']
        target = _path(project, record['path'])
        if not target.exists():
            continue
        target = _path(project, target, file=True)
        if _stable_identity(target.stat()) != intent['file_id']:
            # Return no claim. _deletion_set will preserve/refuse an unowned file.
            continue
        _check_record(project, record, cancelled)
        result.append(published.get(key, dict(record, identity=_identity(target))))
    return result


def _owned_copies(project, target_paths, *, cancelled=None):
    """Validate ownership only for this batch; historical receipts stay intact."""
    rows, candidates = {}, {}
    wanted = {str(path).replace('\\', '/').casefold() for path in target_paths}
    root = _path(project, ARTIFACT_ROOT)
    for path in sorted(root.glob('*/copies.json')):
        receipt = _json(project, path)
        records = [record for record in receipt.get('copies', [])
                   if str(record.get('path', '')).replace('\\', '/').casefold() in wanted]
        if not records:
            continue
        if receipt.get('project_id') != project.project_id or receipt.get('version') != VERSION:
            raise ValueError('Foreign occlusion copy receipt')
        for record in records:
            _cancel(cancelled)
            target = _path(project, record['path'])
            if not target.is_relative_to(project.root / 'proc' / 'workflows') or not target.name.endswith('.mask.png'):
                raise ValueError('Invalid generated mask receipt target')
            if not target.exists():
                continue
            candidates.setdefault(record['path'], []).append(record)
    for path in sorted(root.glob('*/copies.jsonl')):
        # The compact receipt is published once, only after every copy succeeds.
        if (path.parent / 'copies.json').exists():
            continue
        for record in _journal_records(project, path, wanted, cancelled):
            candidates.setdefault(record['path'], []).append(record)
    for relative, records in candidates.items():
        target = _path(project, relative, file=True)
        matching = [record for record in records if _identity(target) == record['identity']]
        if not matching:
            raise ValueError('Generated mask was replaced; ownership is unconfirmed')
        # After a deliberate Skip and reapply, old receipts remain immutable
        # history. Only a receipt for the current file identity can own it.
        record = matching[-1]
        _check_record(project, record, cancelled)
        rows[relative] = record
    return rows


def _deletion_set(project, masks, owned, cancelled=None):
    targets = []
    for row in masks:
        if row['path'] not in owned:
            raise ValueError('Unowned mask files remain; preserve them and resolve ownership explicitly')
        record = owned[row['path']]
        target = _check_record(project, record, cancelled)
        if _identity(target) != record['identity']:
            raise ValueError('Mask copy ownership changed')
        targets.append((target, record))
    return targets


def _remove_owned(project, targets, cancelled=None):
    for target, record in targets:
        _cancel(cancelled)
        _check_record(project, record, cancelled)
        if _identity(target) != record['identity']:
            raise ValueError('Mask copy ownership changed')
        target.unlink()


def _promote_exclusive(source, target):
    """Rename without replacement, preserving the prepared file's identity."""
    if os.name == 'nt':
        # Windows os.rename never replaces an existing destination. The shared
        # replace_file helper deliberately replaces, so is unsafe for this step.
        os.rename(source, target)
    else:
        # Do not emulate exclusive rename with an exists check or hard links:
        # either can leave an unproven/aliased target after a crash.
        import ctypes
        library = ctypes.CDLL(None, use_errno=True)
        rename = getattr(library, 'renameat2', None)
        if rename is None:
            raise OSError('Atomic exclusive rename is unavailable on this platform')
        if rename(-100, ctypes.c_char_p(os.fsencode(source)), -100,
                  ctypes.c_char_p(os.fsencode(target)), 1) != 0:
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code), str(target))


def _copy_budget(live, mapping, body, confirmed_by):
    """Encoded copy bytes plus linear journal/receipt/decision headroom.

    A copy is renamed from its temporary, not duplicated. Four record budgets
    cover prepared/published journal entries and the final receipt/decision.
    Identity integers are budgeted at 128 bits; escaped paths are counted as
    serialized bytes. Metadata headroom remains reserved during the copy loop.
    """
    metadata = 65536 + 2 * len(json.dumps(dict(groups=body['groups'], mappings=list(mapping.values()),
        parameters=body['parameters'], parameter_schema=body['parameter_schema'],
        confirmed_by=confirmed_by), indent=2).encode('utf-8'))
    remaining = 0
    for row in live['copies']:
        if row['image_id'] not in mapping:
            continue
        master = mapping[row['image_id']]['mask']
        remaining += master['bytes']
        record = dict(path=row['path'] + '.mask.png', image_id=row['image_id'],
                      sha256=master['sha256'], bytes=master['bytes'], identity=[2**128 - 1] * 4)
        metadata += 4 * len(json.dumps(record, indent=2).encode('utf-8')) + 4096
    return remaining, metadata


def _copy_mask(project, target, content, expected_sha, *, journal, image_id):
    """Prepare durable identity before exclusive promotion; never claim by hash."""
    opened = None
    temporary = journal.folder / (uuid4().hex + '.partial')
    try:
        with temporary.open('xb') as stream:
            opened = os.fstat(stream.fileno())
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        prepared = _record(project, temporary)
        if prepared['sha256'] != expected_sha:
            raise ValueError('Prepared mask copy changed during publication')
        prepared.update(path=_relative(project, target), image_id=image_id)
        file_id = _stable_identity(opened)
        if _stable_identity(temporary.stat()) != file_id:
            raise ValueError('Exclusively created mask temporary was replaced')
        journal.append(dict(event='prepared', record=prepared,
                            temporary=_relative(project, temporary), file_id=file_id))
        if _stable_identity(temporary.stat()) != file_id:
            raise ValueError('Prepared mask file was replaced')
        _promote_exclusive(temporary, target)
        record = _record(project, target)
        if record['sha256'] != expected_sha or _stable_identity(target.stat()) != file_id:
            raise ValueError('New mask copy changed during publication')
        record.update(identity=_identity(target), image_id=image_id)
        journal.append(dict(event='published', record=record))
        return record
    except BaseException:
        for path in (temporary, target):
            if opened is not None and path.exists() and not path.is_symlink():
                current = path.stat()
                if current.st_nlink == 1 and _stable_identity(current) == _stable_identity(opened):
                    actual = path.read_bytes()
                    if len(actual) <= len(content) and actual == content[:len(actual)]:
                        path.unlink()
        raise


def apply(project, context, payload, confirmed_by, *, accepted_block_ids=None, cancelled=None, progress=None):
    _mutation_guard(project)
    live = _fresh(project, context, cancelled, progress)
    body = _manifest(project, payload, 'generation')
    if (body['decision'] != 'generated' or body['batch_fingerprint'] != live['batch_fingerprint']
            or body['selection_hash'] != live['selection_hash']):
        raise ValueError('Generated proposal is stale; regenerate masks')
    if not isinstance(confirmed_by, str) or not confirmed_by.strip():
        raise ValueError('Explicit reviewer identity is required')
    candidates = {g['group_id']: g for g in body['groups'] if g['status'] == 'candidate_review_required'}
    accepted = set(candidates if accepted_block_ids is None else accepted_block_ids)
    if not accepted or not accepted <= candidates.keys():
        raise ValueError('Select at least one reviewable candidate; blocked groups cannot be applied')
    # Resolve every old target before publication/removal. A replacement Apply
    # never requires changing the current generated review into a Skip first.
    target_paths = [row['path'] + '.mask.png' for row in live['copies']]
    old_targets = _deletion_set(project, live['existing_masks'], _owned_copies(project, target_paths, cancelled=cancelled), cancelled)
    frames = {row['image_id']: row for row in live['frames']}
    # One encoded master per accepted block, regardless of member/overlap count.
    _reserve(project, sum(frames[candidates[key]['image_ids'][0]]['width']
                          * frames[candidates[key]['image_ids'][0]]['height'] * 2
                          + 65536 + candidates[key]['assessment']['bytes'] * 3 for key in accepted))
    folder, mapping = _new_folder(project), {}
    for key in sorted(accepted):
        _cancel(cancelled)
        group = candidates[key]
        for record in group['preview_records']:
            _check_record(project, record, cancelled)
        assessment = _json(project, _check_record(project, group['assessment'], cancelled))
        if assessment['image_ids'] != group['image_ids'] or assessment['batch_id'] != key:
            raise ValueError('Candidate membership differs from canonical temporal block')
        approval = engine.approve_temporal_mask(assessment, assessment_hash=assessment['assessment_hash'], confirmed_by=confirmed_by)
        master = engine.publish_temporal_mask(assessment, approval, output_dir=folder / 'masters', selection_hash=live['selection_hash'])
        record = _record(project, master['output_path'], cancelled)
        for image_id in group['image_ids']:
            if image_id not in frames or image_id in mapping:
                raise ValueError('Canonical image has conflicting mask assignments')
            mapping[image_id] = dict(image_id=image_id, group_id=key, mask=record,
                                    image=live['images'][image_id],
                                    width=master['width'], height=master['height'],
                                    convention='white_includes_black_excludes')
    current = _fresh(project, live, cancelled)
    if current['existing_masks'] != live['existing_masks']:
        raise ValueError('Mask set changed during proposal publication')
    remaining, metadata_budget = _copy_budget(live, mapping, body, confirmed_by)
    # Actual encoded bytes are known now. Refuse before removing any old mask.
    _reserve(project, remaining + metadata_budget)
    # Revalidate ALL old masks after masters are ready, before the first unlink.
    old_targets = _deletion_set(project, current['existing_masks'], _owned_copies(project, target_paths, cancelled=cancelled), cancelled)
    _remove_owned(project, old_targets, cancelled)
    receipt = dict(version=VERSION, project_id=project.project_id, batch_root=live['batch_root'], copies=[])
    journal = _CopyJournal(project, folder, live['batch_root'])
    cached_master, content = None, None
    try:
        for copy in live['copies']:
            if copy['image_id'] not in mapping:
                continue
            _cancel(cancelled)
            if len(receipt['copies']) % 128 == 0:
                _reserve(project, remaining + metadata_budget)
            master = mapping[copy['image_id']]['mask']
            key = (master['path'], master['sha256'], master['bytes'])
            if key != cached_master:
                source = _check_record(project, master, cancelled)
                content = source.read_bytes()
                if hashlib.sha256(content).hexdigest() != master['sha256']:
                    raise ValueError('Master mask changed during copy')
                cached_master = key
            target = _path(project, copy['path'] + '.mask.png')
            record = _copy_mask(project, target, content, master['sha256'], journal=journal, image_id=copy['image_id'])
            receipt['copies'].append(record)
            remaining -= master['bytes']
            if progress:
                progress('copy', len(receipt['copies']), len(live['copies']), str(target))
        _reserve(project, metadata_budget)
        write_json(folder / 'copies.json', receipt)
        _fresh(project, live, cancelled)
        decision = dict(schema=1, version=VERSION, project_id=project.project_id, decision='applied',
            batch_fingerprint=live['batch_fingerprint'], selection_hash=live['selection_hash'],
            confirmed_by=confirmed_by.strip(), generation_manifest=payload['generation_manifest'],
            generation_sha256=payload['generation_sha256'], mappings=list(mapping.values()), copies=receipt['copies'],
            groups=body['groups'], parameters=body['parameters'], parameter_schema=body['parameter_schema'])
        canonical = _immutable(project, folder / 'decision.json', decision)
        return dict(decision, canonical_manifest=canonical['path'], canonical_sha256=canonical['sha256'])
    except BaseException:
        # Cancellation cannot leave a partially installed, apparently approved set.
        for record in receipt['copies']:
            target = _check_record(project, record)
            if _identity(target) != record['identity']:
                raise ValueError('Partial mask copy was replaced; preserve and reconcile it')
            target.unlink()
        raise
    finally:
        journal.close()


def skip(project, context, reason, confirmed_by, *, cancelled=None, progress=None):
    _mutation_guard(project)
    live = _fresh(project, context, cancelled, progress)
    if not all(isinstance(v, str) and v.strip() for v in (reason, confirmed_by)):
        raise ValueError('Explicit skip reason and reviewer identity are required')
    owned = _owned_copies(project, [row['path'] + '.mask.png' for row in live['copies']], cancelled=cancelled)
    # Validate the complete deletion set before deleting anything. Only exact
    # receipt-owned files in this current batch are eligible, never glob cleanup.
    targets = _deletion_set(project, live['existing_masks'], owned, cancelled)
    _reserve(project, 65536)
    _remove_owned(project, targets, cancelled)
    live = _fresh(project, live, cancelled)
    if live['existing_masks']:
        raise ValueError('Mask files appeared during Skip; no decision was approved')
    folder = _new_folder(project)
    body = dict(schema=1, version=VERSION, project_id=project.project_id, decision='skipped',
                batch_fingerprint=live['batch_fingerprint'], selection_hash=live['selection_hash'],
                reason=reason.strip(), confirmed_by=confirmed_by.strip(), mappings=[], copies=[], groups=[])
    canonical = _immutable(project, folder / 'decision.json', body)
    return dict(body, canonical_manifest=canonical['path'], canonical_sha256=canonical['sha256'])


def validate(project, context=None, payload=None, *, cancelled=None, progress=None):
    live = globals()['context'](project, cancelled=cancelled, progress=progress) if context is None else _fresh(project, context, cancelled, progress)
    if payload is None:
        payload = ReviewStore(project).require_occlusion_review(live['batch_fingerprint'])['payload']
    body = _manifest(project, payload, 'canonical')
    if (body['batch_fingerprint'] != live['batch_fingerprint'] or body['selection_hash'] != live['selection_hash']
            or body['decision'] not in ('applied', 'skipped') or not body.get('confirmed_by')):
        raise ValueError('Occlusion decision is stale or unconfirmed')
    expected = {}
    mapping = {row['image_id']: row for row in body['mappings']}
    if len(mapping) != len(body['mappings']):
        raise ValueError('Duplicate canonical mask assignment')
    frames = {row['image_id']: row for row in live['frames']}
    if not mapping.keys() <= frames.keys():
        raise ValueError('Mask assignment refers to a foreign image')
    checked = set()
    for row in mapping.values():
        frame = frames[row['image_id']]
        if row.get('image') != live['images'][row['image_id']]:
            raise ValueError('Canonical mask mapping has foreign selected-image provenance')
        key = (row['mask']['path'], row['mask']['sha256'], row['mask']['bytes'], frame['width'], frame['height'], row['convention'])
        if key in checked:
            continue
        mask = _check_record(project, row['mask'], cancelled)
        with Image.open(mask) as image:
            colors = image.getcolors(3)
            if (image.mode != 'L' or image.size != (frame['width'], frame['height'])
                    or colors is None or {value for count, value in colors} - {0, 255}
                    or row['convention'] != 'white_includes_black_excludes'):
                raise ValueError('Canonical mask is not a full-resolution native binary mask')
        checked.add(key)
    for copy in live['copies']:
        if copy['image_id'] in mapping:
            expected[copy['path'] + '.mask.png'] = mapping[copy['image_id']]['mask']['sha256']
    actual = {row['path']: row['sha256'] for row in live['existing_masks']}
    if actual != expected or (body['decision'] == 'applied' and not mapping) or (body['decision'] == 'skipped' and (mapping or not body.get('reason'))):
        raise ValueError('Actual batch masks differ from the canonical decision')
    receipts = _owned_copies(project, [row['path'] + '.mask.png' for row in live['copies']], cancelled=cancelled)
    if any(path not in receipts for path in expected) or {row['path']: row['sha256'] for row in body['copies']} != expected:
        raise ValueError('Generated mask copy ownership/coverage is incomplete')
    return dict(body, canonical_manifest=payload['canonical_manifest'], canonical_sha256=payload['canonical_sha256'])


def validate_external(manifest_path, expected_sha256, selection_manifest, batch_root=None, *, project_file=None):
    """Native driver gate using the same project census/decision validator.

    Drivers opt in when RS_SELECTION_MANIFEST exists; legacy probe lanes do not
    call this API. Environment paths never override the approved project record.
    """
    from .project_workspace import ProjectDocument
    selected = Path(selection_manifest).absolute()
    roots = [path for path in selected.parents if (path / '.rovscan-owner.json').exists()]
    if len(roots) != 1:
        raise ValueError('Selection manifest requires exactly one project ownership root')
    root = roots[0]
    configured = os.environ.get('RS_PROJECT_FILE') if project_file is None else project_file
    if configured is None:
        documents = sorted(root.glob('*.rovscan'))
        if len(documents) != 1:
            raise ValueError('Native mask gate requires explicit RS_PROJECT_FILE when project documents are ambiguous')
        document = documents[0]
    else:
        if not isinstance(configured, (str, Path)) or not str(configured).strip() or not Path(configured).is_absolute():
            raise ValueError('Explicit project_file/RS_PROJECT_FILE must be an absolute project document path')
        document = Path(configured)
    project = ProjectDocument.load(document)
    if project.root != root:
        raise ValueError('Project root does not match selection ownership')
    _path(project, document, file=True)
    workflow = ReviewStore(project).read('workflow')['payload']
    if _path(project, workflow['selection_manifest'], file=True) != _path(project, selected, file=True):
        raise ValueError('Native driver selected a foreign selection manifest')
    expected_batch = _path(project, _path(project, workflow['root']) / 'batched_images_by_zone')
    if batch_root is not None and _path(project, batch_root) != expected_batch:
        raise ValueError('Native driver selected a different batch root')
    decision = validate(project)
    if (_path(project, decision['canonical_manifest'], file=True) != _path(project, manifest_path, file=True)
            or decision['canonical_sha256'] != expected_sha256):
        raise ValueError('Native driver mask manifest differs from the approved current decision')
    return dict(decision, project_root=str(project.root))
