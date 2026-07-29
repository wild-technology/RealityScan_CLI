#!/usr/bin/env python3
"""Publish every exported component of a workspace to Cesium ion and/or Nira.

Loops exports/<component>/obj (the format BOTH platforms recommend for
photogrammetry) and drives publish_cesium.py / publish_nira.py per component.
Each destination activates only when its credentials are present, and
--dry-run previews every command without uploading anything:

    Cesium ion   CESIUM_ION_TOKEN env var (assets:write + assets:read)
    Nira         NIRACLIENT_DIR env var -> a configured niraclient checkout
                 (Enterprise plan; run `nira.py configure` once)

Results land in <workspace>/publish_report.json so WildScan can show them.

Usage:
    py -3.13 publish_batch.py --workspace F:/na156_h2024_v2 \
        --prefix "IN-401" [--input-crs EPSG:32604] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent

logger = logging.getLogger('publish_batch')


def run(argv: list[str], dry_run: bool) -> dict:
    printable = ' '.join(a if ' ' not in a else f'"{a}"' for a in argv)
    if dry_run:
        logger.info('DRY RUN: %s', printable)
        return {'command': printable, 'dry_run': True}
    logger.info('running: %s', printable)
    proc = subprocess.run(argv, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)
    if proc.stdout:
        logger.info('%s', proc.stdout.strip()[-2000:])
    if proc.returncode != 0:
        logger.error('failed (%d): %s', proc.returncode,
                     (proc.stderr or '').strip()[-2000:])
    return {'command': printable, 'returncode': proc.returncode,
            'success': proc.returncode == 0}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--prefix', required=True,
                        help='asset-name prefix, e.g. the wreck name')
    parser.add_argument('--input-crs', default=None,
                        help='EPSG of the georeferenced exports')
    parser.add_argument('--components', nargs='*', default=None,
                        help='subset of component names (default: all exported)')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    exports = Path(args.workspace) / 'exports'
    if not exports.is_dir():
        raise SystemExit(f'no exports directory under {args.workspace}')

    cesium_token = os.environ.get('CESIUM_ION_TOKEN')
    nira_dir = os.environ.get('NIRACLIENT_DIR')
    if not cesium_token:
        logger.warning('CESIUM_ION_TOKEN not set - Cesium uploads inactive')
    if not nira_dir:
        logger.warning('NIRACLIENT_DIR not set - Nira uploads inactive '
                       '(Enterprise plan + configured niraclient required)')
    if not (cesium_token or nira_dir or args.dry_run):
        raise SystemExit('no destination configured and not --dry-run - '
                         'nothing to do')

    report: dict = {'started': time.strftime('%Y-%m-%d %H:%M:%S'),
                    'assets': []}
    comps = sorted(p for p in exports.iterdir()
                   if p.is_dir() and (p / 'obj').is_dir()
                   and any((p / 'obj').iterdir()))
    if args.components:
        wanted = set(args.components)
        comps = [c for c in comps if c.name in wanted]
    if not comps:
        raise SystemExit('no exported obj/ components found')

    for comp in comps:
        name = f'{args.prefix} {comp.name}'
        entry: dict = {'component': comp.name, 'asset_name': name}
        if cesium_token or args.dry_run:
            argv = [sys.executable, str(REPO / 'publish_cesium.py'),
                    '--name', name, '--dir', str(comp / 'obj'), '--poll']
            if args.input_crs:
                argv += ['--input-crs', args.input_crs]
            entry['cesium'] = run(argv, args.dry_run)
        if nira_dir or args.dry_run:
            argv = [sys.executable, str(REPO / 'publish_nira.py'),
                    '--name', name, '--dir', str(comp / 'obj'),
                    '--niraclient', nira_dir or '<NIRACLIENT_DIR>']
            if args.dry_run:
                argv.append('--dry-run')
            entry['nira'] = run(argv, args.dry_run)
        report['assets'].append(entry)
        with open(Path(args.workspace) / 'publish_report.json', 'w',
                  encoding='utf-8') as fh:
            json.dump(report, fh, indent=2)

    ok = all(r.get('success', True)
             for a in report['assets']
             for r in (a.get('cesium'), a.get('nira')) if r)
    logger.info('published %d component(s); report: %s',
                len(report['assets']),
                Path(args.workspace) / 'publish_report.json')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
