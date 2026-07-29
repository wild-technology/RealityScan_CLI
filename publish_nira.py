#!/usr/bin/env python3
"""Upload a RealityScan export to Nira as a photogrammetry asset.

RealityScan 2.2 has a built-in "Upload to Nira" (Share tab) but it is
GUI-only. The scripted path is Nira's official client
(github.com/NiraOfficial/niraclient) - NOTE it requires a Nira ENTERPRISE
plan; Individual/Professional accounts are browser-upload only. This wrapper
builds the recommended JSON file list (Nira's docs: image files auto-detect
unreliably, so every file is typed explicitly) and drives `nira.py`.

Nira format guidance for RealityScan (help.nira.app article 5591333681307):
OBJ, "Save mesh by parts: Yes", NO vertex colors, decimal-6 numbers, matched
cartesian project/output CRS - which is exactly what
ExportDeliverables.bat's OBJ export produces. Include the .rcInfo file (it
carries georeferencing) and the .mtl + textures. PLY point clouds are NOT
accepted (LAS/LAZ/E57 only) and point clouds must be part of the INITIAL
upload - they cannot be appended later.

One-time setup:
    git clone https://github.com/NiraOfficial/niraclient
    py -3.13 niraclient/nira.py configure     (org admin API key)

Example:
    py -3.13 publish_nira.py --name "IN-401 hull" \
        --dir F:/na156_h2024_v2/exports/cluster_0_a2_c0/obj \
        --niraclient C:/tools/niraclient
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger('publish_nira')

GEOMETRY = {'.obj', '.fbx', '.dae', '.gltf', '.glb'}
MATERIAL = {'.mtl'}
TEXTURE = {'.jpg', '.jpeg', '.png', '.tiff', '.tif', '.bmp'}
SIDECAR = {'.rcinfo'}
POINTCLOUD = {'.las', '.laz', '.e57'}


def build_file_list(directory: Path) -> list[dict]:
    entries: list[dict] = []
    for path in sorted(directory.rglob('*')):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext in GEOMETRY or ext in MATERIAL or ext in SIDECAR:
            entries.append({'path': str(path)})
        elif ext in TEXTURE:
            entries.append({'path': str(path), 'type': 'image'})
        elif ext in POINTCLOUD:
            entries.append({'path': str(path)})
    if not any(Path(e['path']).suffix.lower() in GEOMETRY | POINTCLOUD
               for e in entries):
        raise SystemExit(f'no geometry or point cloud found under {directory}')
    return entries


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--name', required=True, help='Nira asset name')
    parser.add_argument('--dir', required=True,
                        help='export directory (obj/ from ExportDeliverables)')
    parser.add_argument('--niraclient', required=True,
                        help='path to a checkout of NiraOfficial/niraclient')
    parser.add_argument('--wait', type=int, default=0,
                        help='seconds to wait for server-side processing '
                             '(0 = do not wait)')
    parser.add_argument('--dry-run', action='store_true',
                        help='print the file list and command, upload nothing')
    args = parser.parse_args()

    nira_py = Path(args.niraclient) / 'nira.py'
    if not nira_py.is_file():
        raise SystemExit(
            f'nira.py not found at {nira_py}. Clone '
            'github.com/NiraOfficial/niraclient and run "nira.py configure" '
            'first (requires a Nira Enterprise plan API key).')

    directory = Path(args.dir)
    if not directory.is_dir():
        raise SystemExit(f'not a directory: {directory}')

    entries = build_file_list(directory)
    payload = json.dumps(entries, indent=2)
    logger.info('%d file(s) for asset %r', len(entries), args.name)

    cmd = [sys.executable, str(nira_py), 'asset', 'create',
           args.name, 'photogrammetry']
    if args.wait:
        cmd += ['--wait-for-asset-processing', str(args.wait)]

    if args.dry_run:
        print(payload)
        print('command:', ' '.join(cmd), '< filelist.json')
        return 0

    proc = subprocess.run(cmd, input=payload, text=True,
                          capture_output=True)
    if proc.stdout:
        logger.info('%s', proc.stdout.strip())
    if proc.returncode != 0:
        logger.error('niraclient failed (%d):\n%s', proc.returncode,
                     proc.stderr.strip())
        return proc.returncode
    return 0


if __name__ == '__main__':
    sys.exit(main())
