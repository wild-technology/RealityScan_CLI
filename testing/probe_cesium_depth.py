#!/usr/bin/env python3
"""Probe: does Cesium ion honour a NEGATIVE (below-ellipsoid) position?

The owner's standing complaint is that "Cesium appears to ignore depth" and
that neither RealityScan's Export nor its Upload-to-Cesium feature ever placed
a wreck at its real depth. Two hypotheses explain that, and they call for
opposite fixes:

  H1  ion REFUSES or clamps heights below the ellipsoid, so an underwater
      asset can never be placed at depth through the API at all.
  H2  ion honours negative heights perfectly, and the depth was simply never
      SENT - RealityScan's own Help says a model "does not have to be
      georeferenced to be uploaded, since it is possible to upload a model and
      later define its approximate position", which is hand-placement at
      roughly sea level.

The three assets already on this account are consistent with H2 (they sit at
ellipsoidal heights of +2.1, +0.0 and +23.7 m, and one is described "Created
in RealityCapture"), but consistency is not proof, and H1 would invalidate the
entire publish design. This probe settles it with a ~2 KB upload.

It also settles the axis convention, which no Cesium documentation states for
a local-frame 3D_CAPTURE upload: the probe mesh is a box with three
DELIBERATELY DISTINCT extents (20 m East x 8 m North x 3 m Up), so the
half-axes ion reports in the tiled asset's own bounding volume say which of
the mesh's axes it treated as up. A Y-up misreading permutes them visibly.

Everything is read back from the asset's own tileset.json - never from the
upload's exit status.

    py -3.13 testing/probe_cesium_depth.py --token <ion token>
    py -3.13 testing/probe_cesium_depth.py --keep     # do not delete after
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

logger = logging.getLogger('probe_cesium_depth')

API = 'https://api.cesium.com'

# A realistic deep-water target: the NA168 H2080 site, whose corrected
# ellipsoidal height this repo computed as -512.46 m.
PROBE_LON = 133.634688
PROBE_LAT = 3.584574
PROBE_HEIGHT = -512.46

# Distinct on every axis so a permutation cannot hide.
EXTENT_EAST, EXTENT_NORTH, EXTENT_UP = 20.0, 8.0, 3.0

TERMINAL = {'COMPLETE', 'ERROR', 'DATA_ERROR'}


def write_probe_obj(path: Path) -> None:
    """A closed box centred on the origin, extents 20 x 8 x 3 m (E, N, Up)."""
    hx, hy, hz = EXTENT_EAST / 2, EXTENT_NORTH / 2, EXTENT_UP / 2
    corners = [(-hx, -hy, -hz), (hx, -hy, -hz), (hx, hy, -hz), (-hx, hy, -hz),
               (-hx, -hy, hz), (hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz)]
    faces = [(1, 2, 3), (1, 3, 4), (5, 7, 6), (5, 8, 7), (1, 5, 6), (1, 6, 2),
             (2, 6, 7), (2, 7, 3), (3, 7, 8), (3, 8, 4), (4, 8, 5), (4, 5, 1)]
    lines = ['# Cesium depth/orientation probe',
             f'# extents E={EXTENT_EAST} N={EXTENT_NORTH} Up={EXTENT_UP} m']
    lines += [f'v {x:.6f} {y:.6f} {z:.6f}' for x, y, z in corners]
    lines += [f'f {a} {b} {c}' for a, b, c in faces]
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def decode_placement(session, asset_id: int) -> dict:
    """Where ion put the asset, and what shape it thinks it is."""
    import numpy as np
    from pyproj import Transformer

    endpoint = session.get(f'{API}/v1/assets/{asset_id}/endpoint',
                           timeout=60).json()
    tileset = session.get(
        endpoint['url'],
        headers={'Authorization': f'Bearer {endpoint["accessToken"]}'},
        timeout=120).json()

    out: dict = {'extras': tileset.get('asset', {}).get('extras', {})}
    transform = tileset.get('root', {}).get('transform')
    if transform:
        matrix = np.asarray(transform, dtype='float64').reshape(4, 4).T
        ecef = matrix[:3, 3]
        lon, lat, height = Transformer.from_crs(
            'EPSG:4978', 'EPSG:4979', always_xy=True).transform(*ecef)
        out.update(lon=float(lon), lat=float(lat), height=float(height))
    # root.boundingVolume.box is the tiler's PADDED octree root cell (a cube
    # - it read 20x20x20 for a 20x8x3 mesh), not the geometry. The real
    # extents are the tightBoundingBox tile metadata, semantic
    # TILE_BOUNDING_BOX, declared in the tileset's own schema.
    tight = (tileset.get('root', {}).get('metadata', {})
             .get('properties', {}).get('tightBoundingBox'))
    if tight:
        out['full_extents'] = [
            round(2 * float(np.linalg.norm(tight[i:i + 3])), 3)
            for i in (3, 6, 9)]
    padded = tileset.get('root', {}).get('boundingVolume', {}).get('box')
    if padded:
        out['root_cell_extents'] = [
            round(2 * float(np.linalg.norm(padded[i:i + 3])), 3)
            for i in (3, 6, 9)]
    out['raw_tileset'] = tileset
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format='%(levelname)s %(message)s')
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--token', default=None)
    parser.add_argument('--keep', action='store_true',
                        help='do not delete the probe asset afterwards')
    parser.add_argument('--staging', default=None)
    parser.add_argument('--json', default=None, help='write the verdict here')
    args = parser.parse_args()

    import boto3  # noqa: F401
    import requests

    token = args.token or os.environ.get('CESIUM_ION_TOKEN')
    if not token:
        raise SystemExit('no token: pass --token or set CESIUM_ION_TOKEN')

    staging = Path(args.staging) if args.staging else REPO / '_probe_cesium'
    staging.mkdir(parents=True, exist_ok=True)
    obj = staging / 'depth_probe.obj'
    write_probe_obj(obj)
    logger.info('probe mesh %s (%d bytes), extents E=%.1f N=%.1f Up=%.1f m',
                obj, obj.stat().st_size, EXTENT_EAST, EXTENT_NORTH, EXTENT_UP)

    session = requests.Session()
    session.headers['Authorization'] = f'Bearer {token}'

    options = {'sourceType': '3D_CAPTURE',
               'position': [PROBE_LON, PROBE_LAT, PROBE_HEIGHT],
               'textureFormat': 'AUTO',
               'geometryCompression': 'NONE'}
    body = {'name': 'DEPTH PROBE - safe to delete',
            'description': ('Automated probe: does ion honour a negative '
                            '(below-ellipsoid) options.position? '
                            'Created by testing/probe_cesium_depth.py.'),
            'type': '3DTILES', 'options': options}
    logger.info('POST /v1/assets options=%s', json.dumps(options))
    response = session.post(f'{API}/v1/assets', json=body, timeout=60)
    if response.status_code >= 400:
        logger.error('ion REFUSED the request (%d): %s',
                     response.status_code, response.text[:2000])
        logger.error('VERDICT: ion rejects this options payload outright')
        return 1
    created = response.json()
    asset_id = created['assetMetadata']['id']
    logger.info('created probe asset %s', asset_id)

    upload = created['uploadLocation']
    client = boto3.client(
        's3', endpoint_url=upload['endpoint'],
        aws_access_key_id=upload['accessKey'],
        aws_secret_access_key=upload['secretAccessKey'],
        aws_session_token=upload['sessionToken'])
    client.upload_file(str(obj), upload['bucket'],
                       upload['prefix'] + obj.name)
    logger.info('uploaded %s', obj.name)

    done = created['onComplete']
    session.request(done['method'], done['url'],
                    json=done.get('fields') or {},
                    timeout=60).raise_for_status()

    status = None
    while status not in TERMINAL:
        asset = session.get(f'{API}/v1/assets/{asset_id}', timeout=60).json()
        status = asset.get('status')
        logger.info('status %s (%s%%)', status, asset.get('percentComplete', 0))
        if status not in TERMINAL:
            time.sleep(10)

    verdict: dict = {'asset_id': asset_id, 'status': status,
                     'asked': {'lon': PROBE_LON, 'lat': PROBE_LAT,
                               'height': PROBE_HEIGHT},
                     'extents_asked': [EXTENT_EAST, EXTENT_NORTH, EXTENT_UP]}

    if status != 'COMPLETE':
        logger.error('tiling ended %s - ion exposes no reason for this state',
                     status)
        verdict['conclusion'] = (
            f'INCONCLUSIVE: tiling failed ({status}). Cannot separate '
            '"ion refuses negative heights" from "the probe mesh was '
            'unacceptable".')
    else:
        actual = decode_placement(session, asset_id)
        verdict['actual'] = {k: v for k, v in actual.items()
                             if k != 'raw_tileset'}
        if 'height' in actual:
            d_height = actual['height'] - PROBE_HEIGHT
            verdict['height_error_m'] = round(d_height, 3)
            logger.info('ASKED  lon=%.6f lat=%.6f h=%.2f m',
                        PROBE_LON, PROBE_LAT, PROBE_HEIGHT)
            logger.info('ACTUAL lon=%.6f lat=%.6f h=%.2f m',
                        actual['lon'], actual['lat'], actual['height'])
            logger.info('height error %+.3f m', d_height)
            if abs(d_height) < 1.0:
                verdict['conclusion'] = (
                    'ion HONOURS negative below-ellipsoid heights. The '
                    'historical sea-surface placements were NOT ion refusing '
                    'the depth - the depth was never sent.')
            elif abs(actual['height']) < 1.0:
                verdict['conclusion'] = (
                    'ion CLAMPED the asset to the ellipsoid (h~0). Negative '
                    'heights are not honoured through options.position.')
            else:
                verdict['conclusion'] = (
                    f'ion placed the asset at h={actual["height"]:.2f} m, '
                    f'{d_height:+.2f} m from the request - neither honoured '
                    'nor clamped. Investigate.')
        else:
            verdict['conclusion'] = (
                'tileset carries NO root transform: ion did not georeference '
                'the asset at all despite options.position.')
        if 'full_extents' in actual:
            logger.info('extents asked E=%.1f N=%.1f Up=%.1f, ion reports %s',
                        EXTENT_EAST, EXTENT_NORTH, EXTENT_UP,
                        actual['full_extents'])
            got = actual['full_extents']
            expected = [EXTENT_EAST, EXTENT_NORTH, EXTENT_UP]
            if all(abs(g - e) < 0.6 for g, e in zip(got, expected)):
                verdict['axis_convention'] = (
                    'Z-up ENU confirmed: extents came back in the order sent')
            else:
                verdict['axis_convention'] = (
                    f'AXES PERMUTED: sent {expected}, got {got} - the local '
                    'frame is not the East-North-Up order assumed')
            logger.info('%s', verdict['axis_convention'])

    logger.info('VERDICT: %s', verdict.get('conclusion'))
    logger.info('asset: https://ion.cesium.com/assets/%s', asset_id)

    if args.json:
        Path(args.json).write_text(json.dumps(verdict, indent=2),
                                   encoding='utf-8')

    if not args.keep:
        deleted = session.delete(f'{API}/v1/assets/{asset_id}', timeout=60)
        logger.info('probe asset %s deleted (%d)', asset_id,
                    deleted.status_code)
    else:
        logger.info('probe asset %s KEPT', asset_id)
    return 0


if __name__ == '__main__':
    sys.exit(main())
