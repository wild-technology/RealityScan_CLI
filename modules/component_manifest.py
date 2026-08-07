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

# The Python-side membership-capture helpers (scan_pose_sidecars,
# members_from_sidecars, _resolve_image_basename, _POSE_TAG,
# _IMAGE_EXTENSIONS) were removed 2026-08-07 (owner-authorised):
# superseded by AlignZone.bat's in-session identity loop, verified
# caller-free since the 2026-07-28 deprecation sweep (root FINDINGS.md).
# They live in git history before this commit.


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
