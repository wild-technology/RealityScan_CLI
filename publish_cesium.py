#!/usr/bin/env python3
"""Publish a RealityScan mesh export to Cesium ion, correctly georeferenced.

RealityScan 2.2's "Share to Cesium ion" button is GUI-only, and its own Help
is explicit that it does not georeference: "Model does not have to be
georeferenced to be uploaded, since it is possible to upload a model and later
define its approximate position." That is exactly what the three assets
already on this ion account show - read back from their own tilesets, they sit
at ellipsoidal heights of +2.1 m, +0.0 m and +23.7 m, i.e. at the sea surface,
despite being deep-water ROV sites. Horizontal placement survived; the
vertical did not.

This script is the scripted equivalent that does place them properly:

    1. read the export's ``.rsInfo`` sidecar for the CRS and transformToModel
    2. resolve the mesh into that global CRS (auto-detected, then validated)
    3. anchor it, convert the anchor's SEA-SURFACE depth to an ELLIPSOIDAL
       height through the EGM2008 geoid, and rewrite the mesh local to it
    4. POST /v1/assets with sourceType=3D_CAPTURE and options.position
    5. upload to the returned S3 location, replay the onComplete notification
    6. poll, then VERIFY by reading the finished tileset's own transform back

Step 6 is the point. RealityScan exits SUCCESS while doing nothing and ion
reports COMPLETE for an asset in the wrong hemisphere, so the only honest
check is a census: decode ``root.transform`` from the tiled asset and assert
it matches the placement we asked for. ``--verify`` does that and is on by
default whenever the script waits for tiling.

Cesium ion wants photogrammetry in LOCAL coordinates centred on the origin,
with placement passed as ``options.position = [longitude, latitude, height]``
in EPSG:4326, height in metres above the WGS84 ellipsoid. Note the documented
caveat: position "is ignored if the source data already contains
georeferencing information", so this script never sends ``inputCrs`` at the
same time - the two are alternative strategies, not complements.

Auth: an ion token with assets:write + assets:read, via --token or
CESIUM_ION_TOKEN.

Dependencies: requests, boto3, pyproj
    py -3.13 -m pip install requests boto3 pyproj

Example:
    py -3.13 publish_cesium.py --name "H2080 wreck" \
        --dir F:/NA168/Zeuss_NA168_H2080/NewModels \
        --flight-log F:/NA168/Zeuss_NA168_H2080/raw_images/flight_log_53N_UTM.txt \
        --poll --verify
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from modules.cesium_placement import (  # noqa: E402
    PlacementError, enable_geoid_network, nav_envelope_from_flight_log,
    plan_placement, rewrite_obj_local,
)

logger = logging.getLogger('publish_cesium')

API = 'https://api.cesium.com'

# Sidecars ion's tiler consumes. Everything else in an export directory
# (.rsInfo, .rcInfo, RealityScan bookkeeping) is deliberately excluded: the
# .rsInfo describes the ORIGINAL global frame, and shipping it beside a mesh
# we have just rewritten into a local frame would be a lie on disk.
TEXTURE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.tga', '.dds'}
COMPANION_EXTENSIONS = {'.mtl'} | TEXTURE_EXTENSIONS

TERMINAL = {'COMPLETE', 'ERROR', 'DATA_ERROR'}
PART_RE = re.compile(r'^(?P<stem>.+)_(?P<index>\d{7})$')

# Verification tolerances. Horizontal is generous because ion recomputes a
# tight bounding box after placing the origin; vertical is tight because the
# whole point of this script is that the depth is right.
DEFAULT_TOLERANCE_M = 5.0
DEFAULT_VERTICAL_TOLERANCE_M = 1.0


def require_deps() -> None:
    missing = []
    for name in ('requests', 'boto3', 'pyproj'):
        try:
            __import__(name)
        except ImportError:
            missing.append(name)
    if missing:
        raise SystemExit(
            f'missing dependencies: {", ".join(missing)}. Install with:\n'
            f'    py -3.13 -m pip install {" ".join(missing)}')


# --------------------------------------------------------------------------
# Selecting the mesh
# --------------------------------------------------------------------------

def select_objs(directory: Path, mode: str) -> list[Path]:
    """The OBJ files to publish, resolving the whole-vs-parts ambiguity.

    A by-parts export writes both ``<stem>.obj`` and ``<stem>_0000000.obj``
    ... for the SAME model (on NA168 H2080: 178,269 vertices whole against
    180,002 across nine parts, the excess being duplicated part boundaries).
    Uploading both would submit the geometry twice, so one set must win and
    the choice is logged rather than made silently.
    """
    objs = sorted(p for p in directory.glob('*.obj') if p.is_file())
    if not objs:
        raise SystemExit(f'no .obj files in {directory}')

    parts: dict[str, list[Path]] = {}
    wholes: dict[str, Path] = {}
    for obj in objs:
        match = PART_RE.match(obj.stem)
        if match:
            parts.setdefault(match.group('stem'), []).append(obj)
        else:
            wholes[obj.stem] = obj

    overlapping = sorted(set(parts) & set(wholes))
    if not overlapping:
        return objs

    # Drop only the LOSING side of each ambiguous group. Anything else in the
    # directory - a second component with no by-parts twin, say - is still
    # published; an earlier version of this filter excluded every unsuffixed
    # OBJ and would have silently dropped those.
    losers: set[Path] = set()
    for stem in overlapping:
        if mode == 'whole':
            losers.update(parts[stem])
        elif mode == 'split':
            losers.add(wholes[stem])
        else:
            raise SystemExit(f'unknown --parts mode {mode!r}')

    chosen = [o for o in objs if o not in losers]
    logger.warning(
        'export holds BOTH a whole model and its by-parts copy for %s; '
        'publishing the %s form and ignoring %d other file(s). '
        'Override with --parts.',
        ', '.join(overlapping), mode, len(losers))
    return chosen


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------

def referenced_companions(objs: list[Path]) -> list[Path]:
    """The .mtl files an OBJ names, and the textures those .mtl files name.

    Following the references matters when a by-parts export sits in the same
    directory as its whole-model twin: copying every texture in the folder
    would ship the unused set too (326 MB against 121 MB on NA168 H2080) and
    hand ion material files that belong to geometry it was never given.
    """
    wanted: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> bool:
        resolved = path.resolve()
        if resolved in seen or not path.is_file():
            return False
        seen.add(resolved)
        wanted.append(path)
        return True

    for obj in objs:
        with obj.open('r', encoding='utf-8', errors='replace') as handle:
            for line in handle:
                if not line.lower().startswith('mtllib'):
                    continue
                for name in line.split()[1:]:
                    mtl = obj.parent / name
                    if not add(mtl):
                        continue
                    with mtl.open('r', encoding='utf-8',
                                  errors='replace') as mhandle:
                        for mline in mhandle:
                            token = mline.strip().split()
                            if len(token) < 2 or not token[0].lower().startswith(
                                    'map_'):
                                continue
                            texture = obj.parent / token[-1]
                            if texture.suffix.lower() in TEXTURE_EXTENSIONS:
                                add(texture)
    return wanted


def stage(localised, staging: Path, sources: list[Path]) -> list[Path]:
    """Write local-frame OBJs plus the materials and textures they name."""
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    staged: list[Path] = []
    for obj, local_points in localised:
        target = staging / obj.name
        rewrite_obj_local(obj, target, local_points)
        staged.append(target)

    companions = referenced_companions(sources)
    if not companions:
        logger.warning(
            'no .mtl was referenced by %s; uploading untextured geometry',
            ', '.join(p.name for p in sources))
    for companion in companions:
        shutil.copy2(companion, staging / companion.name)
        staged.append(staging / companion.name)
    return sorted(set(staged))


# --------------------------------------------------------------------------
# ion REST
# --------------------------------------------------------------------------

def create_asset(session, name: str, description: str, plan: dict,
                 texture_format: str, geometry_compression: str) -> dict:
    """POST /v1/assets for a photogrammetry mesh.

    Fields are exactly those the live OpenAPI spec defines for
    3DCaptureOptions: sourceType, position, inputCrs, geometryCompression,
    textureFormat. ``targetVersion`` is deliberately absent - it was removed
    from the schema when 3D Tiles 1.1 became the only pipeline, and older
    code here still sent it.
    """
    options = {
        'sourceType': '3D_CAPTURE',
        'position': [plan['lon'], plan['lat'], plan['height_ellipsoidal_m']],
        'textureFormat': texture_format,
        'geometryCompression': geometry_compression,
    }
    body = {'name': name, 'description': description,
            'type': '3DTILES', 'options': options}
    logger.info('POST /v1/assets options=%s', json.dumps(options))
    response = session.post(f'{API}/v1/assets', json=body, timeout=60)
    if response.status_code >= 400:
        raise SystemExit(
            f'ion rejected the asset creation ({response.status_code}): '
            f'{response.text[:2000]}')
    return response.json()


def upload_files(upload: dict, files: list[Path], root: Path) -> None:
    import boto3

    client = boto3.client(
        's3',
        endpoint_url=upload['endpoint'],
        aws_access_key_id=upload['accessKey'],
        aws_secret_access_key=upload['secretAccessKey'],
        aws_session_token=upload['sessionToken'])
    total = len(files)
    for index, path in enumerate(files, 1):
        key = upload['prefix'] + path.relative_to(root).as_posix()
        logger.info('[%d/%d] %s (%.1f MB)', index, total, key,
                    path.stat().st_size / 1024 ** 2)
        client.upload_file(str(path), upload['bucket'], key)


def poll_until_done(session, asset_id: int, interval: float = 30.0) -> str:
    while True:
        asset = session.get(f'{API}/v1/assets/{asset_id}',
                            timeout=60).json()
        status = asset.get('status')
        logger.info('asset %s: %s (%s%%)', asset_id, status,
                    asset.get('percentComplete', 0))
        if status in TERMINAL:
            return status
        time.sleep(interval)


# --------------------------------------------------------------------------
# Verification - the census that replaces trusting a status code
# --------------------------------------------------------------------------

def read_tileset_placement(session, asset_id: int) -> dict:
    """Where ion ACTUALLY put an asset, from its own tileset.json.

    ``root.transform`` is a column-major 4x4 whose translation is the ECEF
    origin of the tileset's local frame. Decoding it needs no human and no
    globe.
    """
    import numpy as np
    from pyproj import Transformer

    endpoint = session.get(f'{API}/v1/assets/{asset_id}/endpoint',
                           timeout=60).json()
    tileset = session.get(
        endpoint['url'],
        headers={'Authorization': f'Bearer {endpoint["accessToken"]}'},
        timeout=120).json()

    transform = tileset.get('root', {}).get('transform')
    if not transform:
        return {'georeferenced': False,
                'note': 'tileset root carries no transform'}

    matrix = np.asarray(transform, dtype='float64').reshape(4, 4).T
    ecef = matrix[:3, 3]
    to_geodetic = Transformer.from_crs('EPSG:4978', 'EPSG:4979',
                                       always_xy=True)
    lon, lat, height = to_geodetic.transform(*ecef)

    # The geometry's real size is the tightBoundingBox tile metadata, NOT
    # root.boundingVolume.box - that one is the tiler's padded octree root
    # cell and comes back as a cube regardless of the mesh (verified on the
    # depth probe: a 20 x 8 x 3 m box reported a 20 x 20 x 20 m root cell).
    tight = (tileset.get('root', {}).get('metadata', {})
             .get('properties', {}).get('tightBoundingBox'))
    extents = None
    if tight:
        extents = [2 * float(np.linalg.norm(tight[i:i + 3]))
                   for i in (3, 6, 9)]

    return {
        'georeferenced': True,
        'lon': float(lon), 'lat': float(lat), 'height': float(height),
        'ecef': [float(v) for v in ecef],
        'extents_m': extents,
        'extras': tileset.get('asset', {}).get('extras', {}),
    }


def verify_placement(actual: dict, plan: dict, tolerance_m: float,
                     vertical_tolerance_m: float) -> tuple[bool, list[str]]:
    """Compare where ion put the asset against where we asked for it."""
    import math

    problems: list[str] = []
    if not actual.get('georeferenced'):
        return False, ['ion returned a tileset with no root transform, so the '
                       'asset is NOT georeferenced']

    # Metres per degree at this latitude; good to well under a metre over the
    # few-metre discrepancies this check is meant to catch.
    lat_rad = math.radians(plan['lat'])
    m_per_deg_lat = 111132.92 - 559.82 * math.cos(2 * lat_rad)
    m_per_deg_lon = 111412.84 * math.cos(lat_rad)
    d_north = (actual['lat'] - plan['lat']) * m_per_deg_lat
    d_east = (actual['lon'] - plan['lon']) * m_per_deg_lon
    horizontal = math.hypot(d_east, d_north)
    vertical = actual['height'] - plan['height_ellipsoidal_m']

    if horizontal > tolerance_m:
        problems.append(
            f'horizontal offset {horizontal:.2f} m exceeds {tolerance_m} m '
            f'(asked lon={plan["lon"]:.6f} lat={plan["lat"]:.6f}, '
            f'got lon={actual["lon"]:.6f} lat={actual["lat"]:.6f})')
    if abs(vertical) > vertical_tolerance_m:
        problems.append(
            f'vertical offset {vertical:+.2f} m exceeds '
            f'{vertical_tolerance_m} m (asked h={plan["height_ellipsoidal_m"]:.2f} m, '
            f'got h={actual["height"]:.2f} m)')
        if plan['geoid_model'] != 'NONE' and abs(
                vertical + plan['geoid_n_m']) < vertical_tolerance_m:
            problems.append(
                'the shortfall equals the geoid undulation that was applied, '
                'which means ion did NOT honour the corrected height - '
                'investigate before trusting any depth on this account')
    logger.info('verification: horizontal %.2f m, vertical %+.2f m',
                horizontal, vertical)

    # Extents are the shape check: an axis permutation or a unit error
    # leaves the origin right and the geometry wrong, which no position
    # comparison can see. ion is known to preserve East-North-Up order
    # (depth probe, 2026-08-31: 20 x 8 x 3 m sent, 20 x 8 x 3 m returned).
    actual_extents = actual.get('extents_m')
    if actual_extents:
        expected = plan['extent_m']
        logger.info('extents asked %.1f x %.1f x %.1f m, ion reports '
                    '%.1f x %.1f x %.1f m', *expected, *actual_extents)
        tolerance = max(0.5, 0.02 * max(expected))
        if any(abs(a - e) > tolerance
               for a, e in zip(actual_extents, expected)):
            problems.append(
                f'geometry extents disagree: asked '
                f'{[round(v, 2) for v in expected]} m, ion reports '
                f'{[round(v, 2) for v in actual_extents]} m. If the values '
                'are the same numbers in a different order the local frame '
                'was not read as East-North-Up; if they are scaled the units '
                'were misread.')
    else:
        logger.warning('tileset exposed no tightBoundingBox metadata, so the '
                       'shape could not be checked - position only')
    return (not problems), problems


# --------------------------------------------------------------------------

def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format='%(levelname)s %(message)s')
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--name', required=True, help='ion asset name')
    parser.add_argument('--dir', required=True,
                        help='export directory holding the mesh, its .mtl, '
                             'its textures and the .rsInfo sidecar')
    parser.add_argument('--description', default='',
                        help='Markdown description')
    parser.add_argument('--flight-log', default=None,
                        help='flight log for this dive. Its nav envelope is '
                             'used as a second, independent check on the '
                             'transformToModel reading.')
    parser.add_argument('--parts', default='whole', choices=('whole', 'split'),
                        help='which form to publish when an export holds both '
                             'a whole model and its by-parts copy '
                             '(default: whole)')
    parser.add_argument('--geoid', default='EGM2008',
                        choices=('EGM2008', 'EGM96'),
                        help='geoid model for depth -> ellipsoidal height '
                             '(default: EGM2008)')
    parser.add_argument('--no-geoid', action='store_true',
                        help='skip the vertical datum correction. The asset '
                             'WILL be placed wrong by the local undulation; '
                             'only for a deliberately local-frame upload.')
    parser.add_argument('--no-proj-network', action='store_true',
                        help='do not let PROJ fetch geoid grids from '
                             'cdn.proj.org (requires the grid installed '
                             'locally, else the run fails loudly)')
    parser.add_argument('--staging', default=None,
                        help='where to write the local-frame copy '
                             '(default: <dir>/_cesium_local)')
    parser.add_argument('--texture-format', default='KTX2',
                        choices=('AUTO', 'WEBP', 'KTX2'))
    parser.add_argument('--geometry-compression', default='DRACO',
                        choices=('NONE', 'DRACO', 'MESHOPT', 'QUANTIZATION'))
    parser.add_argument('--token', default=None,
                        help='ion access token (default: CESIUM_ION_TOKEN)')
    parser.add_argument('--poll', action='store_true',
                        help='wait for tiling to finish')
    parser.add_argument('--verify', action='store_true',
                        help='after tiling, read the asset tileset back and '
                             'assert it landed where we asked (implies '
                             '--poll)')
    parser.add_argument('--tolerance-m', type=float,
                        default=DEFAULT_TOLERANCE_M)
    parser.add_argument('--vertical-tolerance-m', type=float,
                        default=DEFAULT_VERTICAL_TOLERANCE_M)
    parser.add_argument('--dry-run', action='store_true',
                        help='plan and stage, print the placement and the '
                             'exact request body, upload nothing')
    parser.add_argument('--plan-json', default=None,
                        help='write the placement plan to this path')
    args = parser.parse_args()

    root = Path(args.dir)
    if not root.is_dir():
        raise SystemExit(f'not a directory: {root}')

    if not args.no_geoid and not args.no_proj_network:
        enable_geoid_network()

    objs = select_objs(root, args.parts)
    logger.info('publishing %d mesh file(s) from %s', len(objs), root)

    nav_envelope = None
    if args.flight_log:
        nav_envelope = nav_envelope_from_flight_log(Path(args.flight_log))
        logger.info('nav envelope from %s: %s',
                    Path(args.flight_log).name, nav_envelope)

    plan, localised = plan_placement(objs, nav_envelope, args.geoid,
                                     apply_geoid=not args.no_geoid)
    logger.info('CRS %s, transformToModel read as %s',
                plan['crs'], plan['interpretation'])
    logger.info('anchor lon=%.6f lat=%.6f  depth %.2f m + geoid N %+.2f m '
                '= ellipsoidal h %.2f m',
                plan['lon'], plan['lat'], plan['depth_msl_m'],
                plan['geoid_n_m'], plan['height_ellipsoidal_m'])
    logger.info('extent %.1f x %.1f x %.1f m over %d vertices',
                *plan['extent_m'], plan['vertex_count'])

    if args.plan_json:
        Path(args.plan_json).write_text(json.dumps(plan, indent=2),
                                        encoding='utf-8')

    staging = Path(args.staging) if args.staging else root / '_cesium_local'
    staged = stage(localised, staging, objs)
    total_mb = sum(p.stat().st_size for p in staged) / 1024 ** 2
    logger.info('staged %d file(s), %.1f MB in %s',
                len(staged), total_mb, staging)

    options_preview = {
        'sourceType': '3D_CAPTURE',
        'position': [plan['lon'], plan['lat'], plan['height_ellipsoidal_m']],
        'textureFormat': args.texture_format,
        'geometryCompression': args.geometry_compression,
    }
    if args.dry_run:
        logger.info('DRY RUN - nothing uploaded. Request body would be:\n%s',
                    json.dumps({'name': args.name,
                                'description': args.description,
                                'type': '3DTILES',
                                'options': options_preview}, indent=2))
        return 0

    require_deps()
    import requests

    token = args.token or os.environ.get('CESIUM_ION_TOKEN')
    if not token:
        raise SystemExit('no token: pass --token or set CESIUM_ION_TOKEN')

    session = requests.Session()
    session.headers['Authorization'] = f'Bearer {token}'

    created = create_asset(session, args.name, args.description, plan,
                           args.texture_format, args.geometry_compression)
    asset_id = created['assetMetadata']['id']
    logger.info('created ion asset %s', asset_id)

    upload_files(created['uploadLocation'], staged, staging)

    done = created['onComplete']
    response = session.request(done['method'], done['url'],
                               json=done.get('fields') or {}, timeout=60)
    response.raise_for_status()
    logger.info('upload complete - ion tiling started')

    url = f'https://ion.cesium.com/assets/{asset_id}'
    if not (args.poll or args.verify):
        logger.info('asset %s: %s', asset_id, url)
        return 0

    status = poll_until_done(session, asset_id)
    if status != 'COMPLETE':
        logger.error(
            'tiling ended in %s. ion exposes no machine-readable reason for '
            'this state; inspect the asset at %s', status, url)
        return 1

    if not args.verify:
        logger.info('asset %s: %s', asset_id, url)
        return 0

    actual = read_tileset_placement(session, asset_id)
    ok, problems = verify_placement(actual, plan, args.tolerance_m,
                                    args.vertical_tolerance_m)
    if not ok:
        for problem in problems:
            logger.error('PLACEMENT CHECK FAILED: %s', problem)
        logger.error('asset %s tiled but is NOT where it was asked to be: %s',
                     asset_id, url)
        return 1
    logger.info('placement VERIFIED against the asset\'s own tileset')
    logger.info('asset %s: %s', asset_id, url)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except PlacementError as exc:
        logger.error('%s', exc)
        sys.exit(2)
