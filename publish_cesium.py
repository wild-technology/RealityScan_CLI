#!/usr/bin/env python3
"""Upload a RealityScan mesh export to Cesium ion as a tiled 3D asset.

RealityScan 2.2's "Share to Cesium ion" button is GUI-only - the CLI surface
has no publish command (verified against the official command list,
2026-07-29). This script is the scripted equivalent, using ion's documented
REST flow:

    1. POST /v1/assets            (type=3DTILES, sourceType=3D_CAPTURE)
    2. upload the files to the returned S3 location (12 h credentials)
    3. POST the onComplete notification
    4. poll GET /v1/assets/<id> until COMPLETE / error

Cesium staff guidance for RealityScan: upload the RAW mesh (OBJ recommended)
so ion's Reality Tiler processes it - ion hosts a pre-tiled 3D Tiles export
as-is without reprocessing. Multi-texture meshes (e.g. 4 x 16K) are supported
by the current tiler. Use the OBJ-by-parts export from ExportDeliverables.bat.

Auth: an ion access token with assets:write + assets:read scopes, passed via
--token or the CESIUM_ION_TOKEN environment variable.

Dependencies: requests, boto3   (py -3.13 -m pip install requests boto3)

Example:
    py -3.13 publish_cesium.py --name "IN-401 hull" \
        --dir F:/na156_h2024_v2/exports/cluster_0_a2_c0/obj \
        --input-crs EPSG:32604 --description "NA156 H2024 hull"
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

logger = logging.getLogger('publish_cesium')

API = 'https://api.cesium.com'
# Mesh + sidecars ion's tiler consumes; everything else in the export dir
# (rcInfo, info files) is RealityScan bookkeeping.
UPLOAD_EXTENSIONS = {'.obj', '.mtl', '.fbx', '.dae', '.gltf', '.glb',
                     '.jpg', '.jpeg', '.png', '.bmp', '.tga', '.dds', '.bin'}

TERMINAL = {'COMPLETE', 'ERROR', 'DATA_ERROR'}


def require_deps():
    try:
        import boto3  # noqa: F401
        import requests  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            f'missing dependency: {exc.name}. Install with:\n'
            f'    py -3.13 -m pip install requests boto3') from exc


def gather_files(directory: Path) -> list[Path]:
    files = [p for p in sorted(directory.rglob('*'))
             if p.is_file() and p.suffix.lower() in UPLOAD_EXTENSIONS]
    if not files:
        raise SystemExit(f'no uploadable mesh/texture files under {directory}')
    return files


def create_asset(session, name: str, description: str,
                 input_crs: str | None) -> dict:
    options: dict = {'sourceType': '3D_CAPTURE', 'targetVersion': '1.1',
                     'textureFormat': 'KTX2'}
    if input_crs:
        options['inputCrs'] = input_crs
    body = {'name': name, 'description': description,
            'type': '3DTILES', 'options': options}
    resp = session.post(f'{API}/v1/assets', json=body, timeout=60)
    resp.raise_for_status()
    return resp.json()


def upload_to_s3(upload: dict, files: list[Path], root: Path) -> None:
    import boto3
    s3 = boto3.client(
        's3',
        endpoint_url=upload['endpoint'],
        aws_access_key_id=upload['accessKey'],
        aws_secret_access_key=upload['secretAccessKey'],
        aws_session_token=upload['sessionToken'])
    total = len(files)
    for i, path in enumerate(files, 1):
        key = upload['prefix'] + path.relative_to(root).as_posix()
        size_mb = path.stat().st_size / 1024 ** 2
        logger.info('[%d/%d] %s (%.1f MB)', i, total, key, size_mb)
        s3.upload_file(str(path), upload['bucket'], key)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--name', required=True, help='ion asset name')
    parser.add_argument('--dir', required=True,
                        help='export directory holding the mesh + textures '
                             '(e.g. the obj/ folder from ExportDeliverables)')
    parser.add_argument('--description', default='', help='Markdown description')
    parser.add_argument('--input-crs', default=None,
                        help='EPSG code of a georeferenced export, e.g. '
                             'EPSG:32604. Omit for local coordinates.')
    parser.add_argument('--token', default=None,
                        help='ion access token (default: CESIUM_ION_TOKEN env)')
    parser.add_argument('--poll', action='store_true',
                        help='wait for tiling to finish and report the result')
    args = parser.parse_args()

    require_deps()
    import requests

    token = args.token or os.environ.get('CESIUM_ION_TOKEN')
    if not token:
        raise SystemExit('no token: pass --token or set CESIUM_ION_TOKEN')

    root = Path(args.dir)
    if not root.is_dir():
        raise SystemExit(f'not a directory: {root}')
    files = gather_files(root)
    logger.info('%d file(s), %.1f MB total', len(files),
                sum(p.stat().st_size for p in files) / 1024 ** 2)

    session = requests.Session()
    session.headers['Authorization'] = f'Bearer {token}'

    created = create_asset(session, args.name, args.description, args.input_crs)
    asset_id = created['assetMetadata']['id']
    logger.info('created ion asset %s', asset_id)

    upload_to_s3(created['uploadLocation'], files, root)

    done = created['onComplete']
    resp = session.request(done['method'], done['url'],
                           json=done.get('fields') or {}, timeout=60)
    resp.raise_for_status()
    logger.info('upload complete - ion tiling started')

    if args.poll:
        while True:
            asset = session.get(f'{API}/v1/assets/{asset_id}', timeout=60).json()
            status = asset.get('status')
            pct = asset.get('percentComplete', 0)
            logger.info('status %s (%s%%)', status, pct)
            if status in TERMINAL:
                if status != 'COMPLETE':
                    logger.error('tiling failed: %s', status)
                    return 1
                break
            time.sleep(30)
    logger.info('asset %s: https://ion.cesium.com/assets/%s', asset_id, asset_id)
    return 0


if __name__ == '__main__':
    sys.exit(main())
