"""Component-membership manifests (schema v1).

RealityScan's CLI cannot enumerate a component's images, so membership is
captured at zone-align time - the only moment per-camera XMP identity
still exists (exports from imported-component scenes write ORDINAL
sidecars, finding B10). The identity-capture loop
(AlignZone.bat's in-session successive-difference identity loop (the retired reload-based ExportComponentIdentity.bat lives in archive/legacy_scripts; loaded-scene exports are ordinal - B10)) exports
one component's pose sidecars per RealityScan boot; the pose-bearing
sidecars between two sanitize passes ARE that component's images.

One JSON manifest per component, saved as ``<rsalign>.manifest.json``
next to the exported ``.rsalign``:

    {
      "schema": 1,
      "zone": "zone_1",
      "component": "zone_1_c0",
      "rsalign": "<absolute path to the .rsalign>",
      "images": ["P231C0003_..._edt.jpg", ...],
      "camera_count": 123,
      "bbox_utm": [minx, miny, maxx, maxy]  (or null),
      "quality": {"mean_reproj_px": null},
      "created": "<iso8601>",
      "history": [{"event": "...", "at": "<iso8601>"}]
    }

``bbox_utm`` comes from the ZONE FLIGHT LOG rows of the member images
(``flight_log_*_UTM.txt``: ``name;X;Y;Alt;...``), NOT from the exported
XMP positions - those are grid-anchored local-frame values, not UTM
(finding B10 context, 2026-07-23).

The manifest history list is the audit trail for every later
accept/rollback/twin-drop decision (docs/merge-growth-strategy-2026-07.md,
"Bookkeeping layer").
"""
from __future__ import annotations

import datetime
import glob
import json
import os

SCHEMA_VERSION = 1
MANIFEST_SUFFIX = '.manifest.json'

# Image extensions the pipeline aligns (see RealityScanAlignment.__collect_images).
_IMAGE_EXTENSIONS = ('.png', '.heif', '.jpg', '.jpeg')

_POSE_TAG = 'xcr:Position'


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


# ----------------------------------------------------------------------
# Manifest construction / persistence
# ----------------------------------------------------------------------

def build_manifest(zone: str, component: str, rsalign_path: str,
                   images: list[str], bbox_utm: list[float] | None = None,
                   mean_reproj_px: float | None = None,
                   event: str = 'zone_align_identity_export') -> dict:
    """Schema-v1 manifest dict for one component."""
    now = _now_iso()
    return {
        'schema': SCHEMA_VERSION,
        'zone': zone,
        'component': component,
        'rsalign': os.path.abspath(rsalign_path),
        'images': sorted(images),
        'camera_count': len(images),
        'bbox_utm': list(bbox_utm) if bbox_utm else None,
        'quality': {'mean_reproj_px': mean_reproj_px},
        'created': now,
        'history': [{'event': event, 'at': now}],
    }


def manifest_path_for(rsalign_path: str) -> str:
    """Path of the manifest that describes the given .rsalign."""
    return rsalign_path + MANIFEST_SUFFIX


def write_manifest(manifest: dict, path: str | None = None) -> str:
    """Write a manifest next to its .rsalign (or to an explicit path).

    Returns the path written. ASCII-only output so downstream tooling on
    cp1252 consoles can always cat it.
    """
    if path is None:
        path = manifest_path_for(manifest['rsalign'])
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=True)
        f.write('\n')
    return path


def load_manifest(path: str) -> dict:
    """Load one manifest. Accepts either the manifest path itself or the
    .rsalign path it sits next to."""
    if not path.endswith(MANIFEST_SUFFIX):
        path = manifest_path_for(path)
    with open(path, encoding='utf-8') as f:
        manifest = json.load(f)
    if manifest.get('schema') != SCHEMA_VERSION:
        raise ValueError(
            f'Unsupported manifest schema {manifest.get("schema")!r} in {path} '
            f'(this code understands schema {SCHEMA_VERSION})')
    return manifest


def load_zone_manifests(zone_dir: str) -> list[dict]:
    """All manifests under a zone's export directory (recursive - the
    identity-capture loop writes into a subfolder), sorted by component
    name for determinism."""
    pattern = os.path.join(glob.escape(zone_dir), '**', '*' + MANIFEST_SUFFIX)
    manifests = [load_manifest(p) for p in sorted(glob.glob(pattern, recursive=True))]
    manifests.sort(key=lambda m: (m.get('zone', ''), m.get('component', '')))
    return manifests


def append_history(manifest_path: str, event: str) -> dict:
    """Append an audit event ({'event': ..., 'at': iso8601}) to a stored
    manifest and rewrite it. Returns the updated manifest."""
    manifest = load_manifest(manifest_path)
    manifest['history'].append({'event': event, 'at': _now_iso()})
    write_manifest(manifest, manifest_path if manifest_path.endswith(MANIFEST_SUFFIX)
                   else manifest_path_for(manifest_path))
    return manifest


# ----------------------------------------------------------------------
# Membership capture from XMP sidecars
# ----------------------------------------------------------------------

def scan_pose_sidecars(image_root: str) -> dict[str, str]:
    """Current pose-bearing sidecar state under image_root:
    {absolute sidecar path: file content} for every .xmp that carries
    xcr:Position. Read BEFORE camera_registry.sanitize_and_census, which
    restores sidecars to calibration-only (and would erase membership)."""
    state: dict[str, str] = {}
    for root, _dirs, files in os.walk(image_root):
        for filename in files:
            if not filename.lower().endswith('.xmp'):
                continue
            path = os.path.join(root, filename)
            try:
                with open(path, encoding='utf-8', errors='replace') as f:
                    content = f.read()
            except OSError:
                continue
            if _POSE_TAG in content:
                state[path] = content
    return state


def members_from_sidecars(after, before=()) -> list[str]:
    """Image basenames of the component whose export produced the given
    sidecar delta.

    ``after``/``before`` are sidecar states around ONE export step: either
    mappings {sidecar path: content} (as returned by scan_pose_sidecars -
    only pose-bearing entries count) or plain iterables of sidecar paths
    already known to be pose-bearing. The members are the sidecars that
    GAINED xcr:Position content in the step. When the caller restores
    sidecars to calibration-only between steps (sanitize_and_census),
    ``before`` is simply empty.

    Ordinal sidecars (00000.xmp, ...) carry no identity (finding B10) and
    are skipped. Each member resolves to the actual image basename next
    to the sidecar; a sidecar whose image cannot be found resolves to its
    bare stem.
    """
    def pose_set(state) -> set[str]:
        if isinstance(state, dict):
            return {p for p, content in state.items()
                    if content and _POSE_TAG in content}
        return set(state)

    gained = pose_set(after) - pose_set(before)
    listing_cache: dict[str, dict[str, list[str]]] = {}
    members = []
    for sidecar in sorted(gained):
        stem = os.path.splitext(os.path.basename(sidecar))[0]
        if stem.isdigit():
            continue  # ordinal sidecar - identity lost (B10)
        members.append(_resolve_image_basename(sidecar, listing_cache))
    return sorted(members)


def _resolve_image_basename(sidecar_path: str,
                            listing_cache: dict[str, dict[str, list[str]]]) -> str:
    """Actual image basename for a <stem>.xmp sidecar (RealityScan writes
    sidecars next to their images), matched case-insensitively by stem."""
    directory = os.path.dirname(sidecar_path) or '.'
    stem = os.path.splitext(os.path.basename(sidecar_path))[0]
    by_stem = listing_cache.get(directory)
    if by_stem is None:
        by_stem = {}
        try:
            for entry in os.listdir(directory):
                entry_stem, ext = os.path.splitext(entry)
                if ext.lower() in _IMAGE_EXTENSIONS:
                    by_stem.setdefault(entry_stem.lower(), []).append(entry)
        except OSError:
            pass
        listing_cache[directory] = by_stem
    matches = by_stem.get(stem.lower())
    if matches:
        return sorted(matches)[0]
    return stem


# ----------------------------------------------------------------------
# Georeferenced bounding box from the zone flight log
# ----------------------------------------------------------------------

def bbox_from_flight_log(flight_log_path: str | None,
                         member_basenames: list[str]) -> list[float] | None:
    """[minx, miny, maxx, maxy] (UTM) of the member images' flight-log
    positions, or None when no log / no members matched.

    The log format is the georeference module's semicolon table
    (``filename;X (East);Y (North);Alt;...`` header, then
    ``name;x;y;alt;...`` rows). Rows are matched by basename and by stem
    (case-insensitive) so extension mismatches between the log and the
    aligned images never silently empty the bbox.

    XMP sidecar positions are deliberately NOT used: exports carry
    grid-anchored local-frame coordinates, not UTM (B10 context).
    """
    if not flight_log_path or not os.path.isfile(flight_log_path):
        return None

    wanted: set[str] = set()
    for name in member_basenames:
        lower = name.lower()
        wanted.add(lower)
        wanted.add(os.path.splitext(lower)[0])

    xs: list[float] = []
    ys: list[float] = []
    try:
        with open(flight_log_path, encoding='utf-8', errors='replace') as f:
            for line in f:
                parts = line.strip().split(';')
                if len(parts) < 3:
                    continue
                name = parts[0].strip()
                key = name.lower()
                if key not in wanted and os.path.splitext(key)[0] not in wanted:
                    continue
                try:
                    x = float(parts[1])
                    y = float(parts[2])
                except ValueError:
                    continue  # header or malformed row
                xs.append(x)
                ys.append(y)
    except OSError:
        return None

    if not xs:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]
