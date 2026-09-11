"""Deterministic imagery inventory, mask association, and verified source copies."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import ntpath
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
from uuid import uuid4

from . import camera_registry
from .image_exts import ALL_IMAGE_EXTS, PROCESSABLE_IMAGE_EXTS

# Full decode evidence must never be confused with the older header-only JPEG
# verify() pass. The pixel bound is Pillow's default decompression-warning limit.
IMAGE_VERIFICATION_VERSION = 'full-pixel-decode-v1'
MAX_VERIFICATION_PIXELS = 89_478_485


@dataclass
class SourceItem:
    path: str
    relative_path: str
    kind: str
    size_bytes: int
    mtime_ns: int
    camera: str = ""
    family: str = ""
    timestamp_utc: str = ""
    mask_for: str = ""
    included: bool = True
    exception: str = ""
    sha256: str = ""
    duplicate_of: str = ""
    window_status: str = "unassessed"
    device: int = 0
    file_id: int = 0
    ctime_ns: int = 0


class SourceInventory(list):
    """List-compatible inventory retaining the complete source-tree snapshot.

    Persist source_root, source_fingerprint, dive_window, hashing_complete and
    verification_complete alongside the items; completion must not be inferred
    from the presence of individual file digests after cancellation.
    Reconstruct with SourceInventory(items, source_root=..., fingerprint=...).
    A metadata fingerprint detects ordinary additions/removals/edits; cryptographic
    per-file hashes bind content approval and verify every staged source read.
    It is not a filesystem snapshot against a hostile writer restoring metadata.
    """

    def __init__(self, items=(), *, source_root, fingerprint, dive_window=None,
                 hashing_complete=None, verification_complete=None):
        super().__init__(items)
        self.source_root = str(Path(source_root).resolve())
        self.source_fingerprint = fingerprint
        self.dive_window = dive_window
        self.hashing_complete = hashing_complete
        self.verification_complete = verification_complete


def _check_cancelled(cancelled):
    if cancelled is not None and cancelled():
        raise InterruptedError('Inventory operation cancelled; completed file results retained')


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _tree(source: Path):
    """Sorted, non-following full tree listing; no silent permission skips."""
    def fail(error):
        raise error
    for directory, dirs, files in os.walk(source, followlinks=False, onerror=fail):
        dirs.sort()
        for name in sorted(dirs + files):
            path = Path(directory) / name
            if path.is_symlink() or path.is_junction():
                raise ValueError(f"Source link leaves inventory ownership ambiguous: {path}")
            yield path


def source_fingerprint(source: str | Path, *, cancelled=None) -> str:
    """Cheap names/type/file-metadata digest of the ENTIRE source directory.

    Includes non-image files and new directories so a cached review cannot hide
    additions outside a previously selected images subtree. No content hashing.
    """
    _check_cancelled(cancelled)
    root = Path(source)
    if root.is_symlink() or root.is_junction():
        raise ValueError('Source root must not be a link')
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Source must be a directory')
    digest = hashlib.sha256()
    digest.update(json.dumps([str(root), *_identity(root.stat())]).encode() + b'\n')
    for path in _tree(root):
        _check_cancelled(cancelled)
        info = path.stat()
        record = [path.relative_to(root).as_posix(), 'dir' if path.is_dir() else 'file',
                  *_identity(info)]
        digest.update(json.dumps(record, ensure_ascii=True).encode() + b'\n')
    return digest.hexdigest()


def assert_source_unchanged(items: SourceInventory, *, cancelled=None) -> None:
    if not isinstance(items, SourceInventory):
        raise ValueError('SourceInventory with a persisted tree fingerprint is required')
    observed = source_fingerprint(items.source_root, cancelled=cancelled)
    if observed != items.source_fingerprint:
        raise ValueError('Source tree changed since inventory/review; rescan and approve again; '
                         f'source_root={items.source_root!r}; '
                         f'expected={items.source_fingerprint}; observed={observed}')


def _issue(item: SourceItem, message: str) -> None:
    messages = item.exception.split('; ') if item.exception else []
    if message not in messages:
        item.exception = '; '.join([*messages, message])


def file_hash(path: Path, *, cancelled=None) -> str:
    _check_cancelled(cancelled)
    path = Path(path)
    before = path.stat()
    with path.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        # Python 3.13 Windows stat/fstat can expose different ctime semantics;
        # compare creation/change time only within the same API, not across APIs.
        if _identity(opened)[:4] != _identity(before)[:4]:
            raise ValueError(f'Source changed while opening: {path}')
        if cancelled is None:
            result = hashlib.file_digest(handle, "sha256").hexdigest()
        else:
            digest = hashlib.sha256()
            while True:
                _check_cancelled(cancelled)
                chunk = handle.read(8 * 1024 * 1024)
                _check_cancelled(cancelled)
                if not chunk:
                    break
                digest.update(chunk)
            result = digest.hexdigest()
        after = os.fstat(handle.fileno())
    if (_identity(opened) != _identity(after) or _identity(after)[:4] != _identity(before)[:4]
            or _identity(before) != _identity(path.stat())):
        raise ValueError(f'Source changed during hashing: {path}')
    return result


def is_mask(path: Path) -> bool:
    return ".mask." in path.name.lower() or any(
        part.lower() in (".mask", "_mask", "masks") for part in path.parts[:-1])


def scan_source(source: str | Path) -> SourceInventory:
    """Read file metadata only. Unknown cameras/times/mask matches block staging.

    Discover registered camera filenames anywhere in the source; unknown imagery
    inside explicit imagery trees or raw/still_cam is flagged for classification.
    Unrecognized report/map tiles and AppleDouble resource forks are not survey
    images. Root non-camera TIFFs are numeric map candidates, never converted.
    """
    from geoall import parse_timestamp_from_filename

    before = source_fingerprint(source)
    source = Path(source).resolve(strict=True)
    items = SourceInventory(source_root=source, fingerprint=before)
    for path in _tree(source):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext not in ALL_IMAGE_EXTS and ext != ".xmp":
            continue
        if path.name.startswith('._'):
            continue
        relative = path.relative_to(source)
        parents = {part.casefold() for part in relative.parts[:-1]}
        family = camera_registry.family(path.name) or ''
        map_candidate = path.parent == source and ext in ('.tif', '.tiff') and not family
        explicit_tree = bool(parents & {'images', 'timer_still', 'batched_images_by_zone'})
        raw_stills = 'raw' in parents and 'still_cam' in parents
        if not (family or explicit_tree or raw_stills or path.parent == source or map_candidate):
            continue
        stat = path.stat()
        kind = ('map' if map_candidate else 'mask' if is_mask(path) else
                'sidecar' if ext == '.xmp' else 'image')
        item = SourceItem(str(path), path.relative_to(source).as_posix(), kind,
                          stat.st_size, stat.st_mtime_ns, device=stat.st_dev,
                          file_id=stat.st_ino, ctime_ns=stat.st_ctime_ns)
        item.family = family
        item.camera = camera_registry.FAMILY_CAMERA.get(family, '')
        if kind == "image":
            timestamp = parse_timestamp_from_filename(path.name)
            if timestamp is not None:
                item.timestamp_utc = timestamp.replace(tzinfo=timezone.utc).isoformat()
            issues = []
            if not item.family:
                issues.append("Unrecognised camera; assign a camera or explicitly exclude")
            if timestamp is None:
                item.window_status = 'invalid_timestamp'
                issues.append("No valid UTC timestamp; explicit correction or exclusion required")
            if ext not in PROCESSABLE_IMAGE_EXTS:
                issues.append("Image type not supported by the processing stages")
            if stat.st_size == 0:
                issues.append("Empty image")
            item.exception = "; ".join(issues)
        elif kind == "sidecar":
            # Keep the source metadata in raw. Applying its priors is a separate,
            # approved import policy; do not carry unknown solved poses forward.
            item.included = False
            item.exception = "Existing XMP retained in raw; requires explicit import policy"
        items.append(item)
    images = [item for item in items if item.kind == "image"]
    names, stems = defaultdict(list), defaultdict(list)
    for image in images:
        path = Path(image.path)
        names[(str(path.parent).casefold(), path.name.casefold())].append(image)
        stems[(str(path.parent).casefold(), path.stem.casefold())].append(image)
    for mask in (item for item in items if item.kind == "mask"):
        path = Path(mask.path)
        if ".mask." in path.name.lower():
            name = path.name[:path.name.lower().index(".mask.")]
            matches = names[(str(path.parent).casefold(), name.casefold())]
        else:
            matches = stems[(str(path.parent.parent).casefold(), path.stem.casefold())]
        if len(matches) == 1:
            mask.mask_for = matches[0].path
            mask.camera, mask.family = matches[0].camera, matches[0].family
        else:
            mask.exception = f"Mask matches {len(matches)} images; exactly one is required"
    assert_source_unchanged(items)
    return items


def verify_images(items: list[SourceItem], *, cancelled=None, progress=None,
                  verified_cache: dict | None = None) -> None:
    """Verify structure, fully decode pixels, and check mask dimensions.

    progress(done, total, path) uses included image/mask files as its total.
    Cancellation raises InterruptedError between files, before/after a decoder
    call, and during the dimensions pass; a single Pillow call is not preempted.
    verified_cache holds successful (sha256, width, height) -> True proofs from
    this verification version. Persistent callers must validate the cache's
    provenance/version; arbitrary caller-provided proofs are not trusted data.
    A completed hash pass plus unchanged file identity permits reuse; otherwise
    compute the digest here before considering a decode proof. Headers and mask
    associations are checked on every pass. Failed decodes are never cached.
    Callback errors propagate. A single Pillow load() cannot be preempted.
    """
    from PIL import Image, ImageFile

    if isinstance(items, SourceInventory):
        items.verification_complete = False
    _check_cancelled(cancelled)
    if ImageFile.LOAD_TRUNCATED_IMAGES:
        raise ValueError('Full image verification requires Pillow truncated-image loading disabled')
    cache = {} if verified_cache is None else verified_cache
    hashed = isinstance(items, SourceInventory) and items.hashing_complete is True
    sizes = {}
    eligible = [item for item in items if item.kind in ('image', 'mask') and item.included]
    total = len(eligible)
    for index, item in enumerate(eligible, 1):
        _check_cancelled(cancelled)
        try:
            path = Path(item.path)
            before = path.stat()
            if _identity(before) != (item.device, item.file_id, item.size_bytes, item.mtime_ns, item.ctime_ns):
                raise ValueError('Source changed before pixel verification')
            digest = item.sha256 if hashed and re.fullmatch('[0-9a-f]{64}', item.sha256) else file_hash(path, cancelled=cancelled)
            with Image.open(path) as image:
                sizes[item.path] = image.size
                width, height = image.size
                if width <= 0 or height <= 0 or width * height > MAX_VERIFICATION_PIXELS:
                    raise ValueError(f'Image exceeds verification pixel limit ({MAX_VERIFICATION_PIXELS})')
                key = (digest, width, height)
                if cache.get(key) is not True:
                    image.verify()
                    _check_cancelled(cancelled)
                    # JPEG verify() does not decode entropy-coded pixel data.
                    # Reopen after verify(), then force the complete decoder.
                    with Image.open(path) as decoded:
                        decoded.load()
                        if decoded.size != (width, height):
                            raise ValueError('Image dimensions changed during decode')
            if _identity(before) != _identity(path.stat()):
                raise ValueError('Source changed during pixel verification')
            _check_cancelled(cancelled)
            cache[key] = True
        except InterruptedError:
            raise
        except Exception as exc:
            _issue(item, f"Unreadable {item.kind}: {exc}")
        _check_cancelled(cancelled)
        if progress is not None and index < total:
            progress(index, total, item.path)
    for item in items:
        _check_cancelled(cancelled)
        if item.kind == "mask" and item.included and item.mask_for in sizes:
            if sizes.get(item.path) != sizes[item.mask_for]:
                _issue(item, "Mask dimensions differ from the matching image")
    _check_cancelled(cancelled)
    if progress is not None:
        progress(total, total, eligible[-1].path if eligible else '')
    _check_cancelled(cancelled)
    if isinstance(items, SourceInventory):
        items.verification_complete = True


def apply_dive_window(items: list[SourceItem], launch: str, recovery: str) -> dict:
    """Flag out-of-window imagery; leave include/exclude to the recorded policy."""
    start = datetime.fromisoformat(launch.replace("Z", "+00:00"))
    end = datetime.fromisoformat(recovery.replace("Z", "+00:00"))
    if start.tzinfo is None or end.tzinfo is None or end <= start:
        raise ValueError("Dive window must have ordered, timezone-aware bounds")
    outside = []
    invalid = []
    for item in items:
        if item.kind != "image":
            continue
        # Reapplying a corrected window removes only this check's old finding.
        message = "Image timestamp is outside the recorded dive window"
        item.exception = '; '.join(x for x in item.exception.split('; ') if x != message)
        try:
            instant = datetime.fromisoformat(item.timestamp_utc.replace('Z', '+00:00'))
            if instant.tzinfo is None:
                raise ValueError('Missing timezone')
        except (ValueError, TypeError):
            item.window_status = 'invalid_timestamp'
            _issue(item, 'No valid UTC timestamp; explicit correction or exclusion required')
            invalid.append(item.path)
            continue
        item.window_status = 'in_window' if start <= instant <= end else 'outside_window'
        if not start <= instant <= end:
            _issue(item, message)
            outside.append(item.path)
    result = {"launch_utc": start.isoformat(), "recovery_utc": end.isoformat(),
              "outside_count": len(outside), "outside_paths": outside,
              'invalid_timestamp_count': len(invalid), 'invalid_timestamp_paths': invalid}
    if isinstance(items, SourceInventory):
        items.dive_window = {'launch_utc': start.isoformat(), 'recovery_utc': end.isoformat()}
    return result


def hash_identities(items: list[SourceItem], *, cancelled=None, progress=None,
                    resume: bool = False) -> None:
    """Hash identities, with progress(done, total, path) for ALL inventory files.

    Cancellation is checked within 8 MiB reads (when a callback is supplied),
    tree-fingerprint walks and duplicate classification. A partial pass cannot
    produce an approval token. resume=True reuses completed digests only after
    validating the source-tree fingerprint and each file's recorded identity.
    This is a metadata-validated cache, not protection against malicious metadata
    restoration; staged copies still verify actual bytes against the digests.
    Default resume=False rereads all content. GUI callback errors propagate.
    """
    if isinstance(items, SourceInventory):
        items.hashing_complete = False
    _check_cancelled(cancelled)
    assert_source_unchanged(items, cancelled=cancelled)
    seen = defaultdict(list)
    for index, item in enumerate(items, 1):
        _check_cancelled(cancelled)
        path = Path(item.path)
        before = path.stat()
        if _identity(before) != (item.device, item.file_id, item.size_bytes, item.mtime_ns, item.ctime_ns):
            raise ValueError(f"Source changed since inventory: {path}")
        if not (resume and re.fullmatch('[0-9a-f]{64}', item.sha256)):
            item.sha256 = ''  # Never retain an old digest for an interrupted rehash.
            item.sha256 = file_hash(path, cancelled=cancelled)
        if _identity(path.stat()) != _identity(before):
            raise ValueError(f"Source changed during hashing: {path}")
        if item.kind == 'image':
            item.duplicate_of = ''
            key = (item.camera, path.name.casefold())
            seen[key].append(item)
        if progress is not None and index < len(items):
            progress(index, len(items), item.path)
    for group in seen.values():
        _check_cancelled(cancelled)
        if len({item.sha256 for item in group}) > 1:
            for item in group:
                _check_cancelled(cancelled)
                _issue(item, 'Same camera/filename has different image content')
        else:
            # An explicitly excluded copy must never become the only proc source.
            canonical = min(group, key=lambda im: (not im.included, im.relative_path))
            for item in group:
                _check_cancelled(cancelled)
                if item is not canonical:
                    item.duplicate_of = canonical.path
    assert_source_unchanged(items, cancelled=cancelled)
    if progress is not None:
        progress(len(items), len(items), items[-1].path if items else '')
    _check_cancelled(cancelled)
    items.hashing_complete = True


def approval_token(items: SourceInventory) -> str:
    """Bind content hashes, associations, window, and explicit include decisions."""
    if (not isinstance(items, SourceInventory) or items.hashing_complete is False
            or items.verification_complete is False
            or any(not re.fullmatch('[0-9a-f]{64}', im.sha256) for im in items)):
        raise ValueError('A fully hashed SourceInventory is required for content approval')
    payload = {'source_root': items.source_root, 'source_fingerprint': items.source_fingerprint,
               'dive_window': items.dive_window,
               'items': [asdict(im) for im in sorted(items, key=lambda im: im.relative_path)]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _sidecar_identity_collisions(items, *, cancelled=None) -> list[dict]:
    """Find selected camera/stem identities with distinct image extensions.

    Proc flattens source directories within each camera. RealityScan binds
    <stem>.xmp regardless of image extension (rs-reference 05 section 1.1).
    Same-basename zone copies use the existing content-duplicate policy instead.
    Compute from current decisions so explicit exclusions resolve the diagnostic
    without clearing unrelated exception flags. No selection is changed here.
    """
    groups = defaultdict(list)
    for item in items:
        _check_cancelled(cancelled)
        if item.kind == 'image' and item.included:
            path = Path(item.path)
            groups[((item.camera or 'unknown').casefold(), path.stem.casefold())].append(item)
    collisions = []
    for (camera, stem), group in sorted(groups.items()):
        _check_cancelled(cancelled)
        if len({Path(item.path).name.casefold() for item in group}) > 1:
            collisions.append({'camera': camera, 'sidecar_name': stem + '.xmp',
                               'paths': sorted(item.path for item in group),
                               'reason': 'Sidecar identity collision: selected images share a RealityScan stem.xmp'})
    return collisions


def summarize_inventory(items: list[SourceItem], *, navigation_matches: dict | None = None) -> dict:
    """Camera and exact mount-family censuses, using the same count definitions.

    unique/identical_duplicates use camera + basename + content, preserving
    different exposure names. unique_content_hashes additionally shows equal bytes
    under different names without silently discarding their timestamps.
    sidecar_identity_collisions reports selected cross-extension stem conflicts
    even before content hashing; each camera also has a count of these groups.
    families retains exact SourceItem.family keys (including '' for unassigned).
    Each family row adds family and camera. Mixed camera assignments report
    camera=None, cameras and camera_conflict=True instead of choosing a mount's
    optical identity arbitrarily. Navigation failures join families by image path.
    """
    collisions = _sidecar_identity_collisions(items)
    collision_counts = defaultdict(int)
    family_collision_counts = defaultdict(int)
    camera_groups, family_groups = defaultdict(list), defaultdict(list)
    image_families = {}
    for item in items:
        if item.kind in ('image', 'mask'):
            camera_groups[item.camera or 'unknown'].append(item)
            family_groups[item.family].append(item)
        if item.kind == 'image':
            image_families[item.path] = item.family
    for collision in collisions:
        collision_counts[collision['camera']] += 1
        for family in {image_families[path] for path in collision['paths']}:
            family_collision_counts[family] += 1
    camera_unmatched, family_unmatched = defaultdict(int), defaultdict(int)
    if navigation_matches is not None:
        for row in navigation_matches['unmatched']:
            camera_unmatched[row['camera'] or 'unknown'] += 1
            if row['path'] in image_families:
                family_unmatched[image_families[row['path']]] += 1

    def census_row(group, unmatched, collision_count):
        images = [im for im in group if im.kind == 'image']
        masks = [im for im in group if im.kind == 'mask']
        hashed = all(im.sha256 for im in images)
        groups = defaultdict(set)
        for im in images:
            groups[(im.camera or 'unknown', Path(im.path).name.casefold())].add(im.sha256)
        unique = sum(len(hashes) for hashes in groups.values()) if hashed else None
        return {'total': len(images),
            'in_window': sum(im.window_status == 'in_window' for im in images),
            'outside_window': sum(im.window_status == 'outside_window' for im in images),
            'invalid_timestamp': sum(im.window_status == 'invalid_timestamp' for im in images),
            'unassessed_window': sum(im.window_status == 'unassessed' for im in images),
            'included': sum(im.included for im in images), 'unique': unique,
            'unique_content_hashes': len({im.sha256 for im in images}) if hashed else None,
            'identical_duplicates': len(images) - unique if hashed else None,
            'conflicting_names': sum(len(hashes) > 1 for hashes in groups.values()) if hashed else None,
            'sidecar_identity_collisions': collision_count,
            'masks': len(masks), 'unmatched_masks': sum(not im.mask_for for im in masks),
            'unmatched': unmatched if navigation_matches is not None else None}

    cameras = {camera: census_row(group, camera_unmatched[camera], collision_counts[camera.casefold()])
               for camera, group in sorted(camera_groups.items())}
    families = {}
    for family, group in sorted(family_groups.items()):
        optical_cameras = sorted({im.camera or 'unknown' for im in group})
        row = census_row(group, family_unmatched[family], family_collision_counts[family])
        row.update(family=family, camera=optical_cameras[0] if len(optical_cameras) == 1 else None)
        if len(optical_cameras) > 1:
            row.update(cameras=optical_cameras, camera_conflict=True)
        families[family] = row
    return {'cameras': cameras, 'families': families, 'maps': sum(im.kind == 'map' for im in items),
            'sidecar_identity_collisions': collisions,
            'source_fingerprint': getattr(items, 'source_fingerprint', None),
            'approval_token': approval_token(items) if isinstance(items, SourceInventory)
                              and items.hashing_complete is not False
                              and items.verification_complete is not False
                              and all(im.sha256 for im in items) else None}


def copy_verified(source: Path, target: Path, *, expected_hash: str,
                  reserve_bytes: int, cancelled=lambda: False) -> None:
    """Copy without replacing a different artifact, checking storage per chunk."""
    source, target = Path(source), Path(target)
    before = source.stat()
    if cancelled():
        raise InterruptedError('Copy cancelled')
    if source.is_symlink() or target.is_symlink() or target.is_junction():
        raise ValueError('Copy source/target cannot be redirected')
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if not target.is_file() or target.stat().st_nlink != 1:
            raise ValueError('Cached destination must be a regular independent copy')
        # A cached destination is not proof that the original is still current.
        if file_hash(source) != expected_hash:
            raise ValueError(f'Source changed since approval: {source}')
        if file_hash(target) != expected_hash:
            raise FileExistsError(f"Existing artifact differs: {target}")
        return
    temporary = target.with_name(target.name + "." + uuid4().hex + ".partial")
    try:
        with source.open("rb") as src, temporary.open("xb") as dst:
            while chunk := src.read(8 * 1024 * 1024):
                if cancelled():
                    raise InterruptedError("Copy cancelled; completed verified copies retained")
                if shutil.disk_usage(target.parent).free < reserve_bytes + len(chunk):
                    raise OSError("Free-space reserve reached; copy paused")
                dst.write(chunk)
            dst.flush()
            os.fsync(dst.fileno())
        if file_hash(temporary) != expected_hash:
            raise IOError(f"Copy hash mismatch: {source}")
        if _identity(source.stat()) != _identity(before):
            raise ValueError(f'Source changed during copy: {source}')
        temporary.rename(target)
        shutil.copystat(source, target)
    finally:
        temporary.unlink(missing_ok=True)


def _selection_images_root(project_root: Path, relative: str) -> Path:
    """Resolve a normalized project-relative image tree strictly below proc."""
    if not isinstance(relative, str):
        raise ValueError('images_relative_path must be a normalized relative string under proc')
    parts = relative.split('/')
    if (PureWindowsPath(relative).anchor or '\\' in relative or len(parts) < 2
            or parts[0] != 'proc'
            or any(part in ('', '.', '..') or part.endswith((' ', '.')) or ntpath.isreserved(part)
                   or any(char in part for char in '<>:"|?*')
                   or any(ord(char) < 32 for char in part) for part in parts)):
        raise ValueError('images_relative_path must be normalized and strictly contained under proc')
    target = project_root.joinpath(*parts)
    for path in (target, *target.parents):
        if path.is_symlink() or path.is_junction():
            raise ValueError(f'Image selection tree must not use redirected paths: {path}')
        if path.exists() and not path.is_dir():
            raise ValueError(f'Image selection tree parent is not a directory: {path}')
        if path == project_root:
            break
    if not target.resolve().is_relative_to(project_root / 'proc'):
        raise ValueError('Image selection tree escapes proc')
    return target


def _verify_selection_tree(root: Path, expected: dict[str, str], *,
                           complete: bool, cancelled=None) -> None:
    """Check the exact file manifest and bytes; never remove stale geometry.

    No unexpected file is safe in a solver input tree: even an XMP sidecar can
    alter an import. Empty directories are harmless. The initial check permits
    absent expected files for resume; the final check requires every one.
    """
    found = set()
    if root.exists():
        for path in _tree(root):
            _check_cancelled(cancelled)
            if path.is_dir():
                continue
            key = str(path).casefold()
            if key not in expected or key in found:
                raise FileExistsError(f'Unmanifested file in image selection tree: {path}; choose a fresh tree')
            if not path.is_file() or path.stat().st_nlink != 1:
                raise ValueError(f'Image selection file must be an independent regular file: {path}')
            if file_hash(path, cancelled=cancelled) != expected[key]:
                raise FileExistsError(f'Conflicting existing image/mask content: {path}')
            found.add(key)
    if complete and (missing := expected.keys() - found):
        raise ValueError(f'Image selection tree is incomplete; missing: {min(missing)}')


def stage_inventory(items: list[SourceItem], project_root: Path, *,
                    reserve_bytes: int, approved_token: str | None = None,
                    images_relative_path: str = 'proc/images',
                    cancelled=lambda: False, progress=None) -> dict:
    """Preserve raw originals and create an independent, canonical image tree.

    Every zone later receives copies from this proc tree, including its masks.
    No hardlinks connect solver-writable imagery to raw or external originals.
    images_relative_path is a normalized, slash-separated path below proc; callers
    can use proc/selections/<approval-token>/images for immutable selections.
    Raw preservation always uses raw/imagery. Existing/final selection files must
    match the exact current image/mask manifest and hashes; stale files are refused,
    never deleted. Return images_root is the selected tree's absolute path.
    """
    assert_source_unchanged(items)
    current_token = approval_token(items)
    if approved_token != current_token:
        raise ValueError('Inventory content hash must be explicitly confirmed before staging')
    project_root = Path(project_root).resolve()
    source_root = Path(items.source_root)
    if project_root.is_relative_to(source_root) or source_root.is_relative_to(project_root):
        raise ValueError('Source and project roots must be disjoint')
    collisions = _sidecar_identity_collisions(items, cancelled=cancelled)
    if collisions:
        first = collisions[0]
        raise ValueError(f"Sidecar identity collision at {first['camera']}/{first['sidecar_name']}: "
                         'explicitly exclude conflicting images and confirm the new inventory')
    errors = [item for item in items if item.included and item.exception]
    if errors:
        raise ValueError(f"{len(errors)} unresolved inventory exceptions; first: {errors[0].exception}")
    if any(not item.sha256 for item in items):
        raise ValueError("Inventory must be hashed before staging")
    if any(item.kind == 'image' and item.included and item.window_status != 'in_window' for item in items):
        raise ValueError('Included imagery requires a checked dive window before staging')
    by_path = {item.path: item for item in items}
    proc_images = _selection_images_root(project_root, images_relative_path)
    outputs = []
    # Validate all destinations and mask associations before the first copy.
    destinations = {}
    for item in items:
        if item.kind == 'mask' and item.included and item.mask_for not in by_path:
            raise ValueError('Included mask lacks its inventoried image')
        rel = Path(item.relative_path)
        if rel.is_absolute() or '..' in rel.parts or ':' in item.relative_path or '\\' in item.relative_path:
            raise ValueError('Inventory relative path escapes raw root')
        if Path(item.path).resolve() != (source_root / rel).resolve():
            raise ValueError('Inventory path no longer belongs to its source root')
        if item.included and item.kind == 'image':
            canonical = by_path.get(item.duplicate_of, item)
            if not canonical.included:
                raise ValueError('Duplicate refers to an excluded canonical image; rehash decisions')
            dest = proc_images / canonical.camera / Path(canonical.path).name
        elif item.included and item.kind == 'mask' and by_path[item.mask_for].included:
            image = by_path[item.mask_for]
            canonical = by_path.get(image.duplicate_of, image)
            dest = proc_images / canonical.camera / (Path(canonical.path).name + '.mask' + Path(item.path).suffix)
        else:
            continue
        if not dest.resolve().is_relative_to(proc_images):
            raise ValueError('Canonical image/mask destination escapes the selection tree')
        key = str(dest).casefold()
        if key in destinations and destinations[key] != item.sha256:
            raise ValueError('Conflicting content targets the same canonical image/mask path')
        destinations[key] = item.sha256
    _verify_selection_tree(proc_images, destinations, complete=False, cancelled=cancelled)
    for index, item in enumerate(items):
        rel = Path(item.relative_path)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError("Inventory relative path escapes raw root")
        raw = project_root / "raw/imagery" / rel
        if not raw.resolve().is_relative_to(project_root / "raw"):
            raise ValueError("Raw destination escapes project")
        if Path(item.path).resolve().is_relative_to(project_root):
            raise ValueError("Original imagery must be outside the project")
        copy_verified(Path(item.path), raw, expected_hash=item.sha256,
                      reserve_bytes=reserve_bytes, cancelled=cancelled)
        target = None
        if item.included and item.kind == "image" and not item.duplicate_of:
            target = proc_images / item.camera / Path(item.path).name
        elif item.included and item.kind == "mask":
            image = by_path[item.mask_for]
            if image.included:
                canonical = by_path.get(image.duplicate_of, image)
                target = proc_images / canonical.camera / (Path(canonical.path).name + ".mask" + Path(item.path).suffix)
        elif item.included and item.kind == "map":
            target = project_root / Path(item.path).name
        if target:
            if not target.resolve().is_relative_to(project_root):
                raise ValueError("Processing destination escapes project")
            copy_verified(raw, target, expected_hash=item.sha256,
                          reserve_bytes=reserve_bytes, cancelled=cancelled)
            outputs.append(str(target))
        if progress:
            progress(index + 1, len(items), item.path)
    assert_source_unchanged(items, cancelled=cancelled)
    if approval_token(items) != current_token:
        raise ValueError('Inventory decisions changed during staging')
    _selection_images_root(project_root, images_relative_path)
    _verify_selection_tree(proc_images, destinations, complete=True, cancelled=cancelled)
    return {"images_root": str(proc_images), "outputs": outputs,
            'images_relative_path': images_relative_path,
            'input_inventory_hash': current_token, 'source_fingerprint': items.source_fingerprint,
            "items": [asdict(item) for item in items]}
