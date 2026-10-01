#!/usr/bin/env python3
"""Export every named component's camera registration from a saved project.

Thin driver over ``ExportRegistrations.bat`` (one RealityScan session, per
component ``-selectComponent`` + ``-exportRegistration``, NEVER a ``-save``),
run through ``RealityScanCLI.run_batch_script`` like every other workflow
(hard rule 1).

Why it exists: a project assembled by hand (NA165/H2060 Merged_v2, whose
components the operator renamed ``Component N``) has no merge report, so
run_models' scale gate cannot run on it and nothing records which cameras
each component holds. The registration CSV answers both without a mesh:
the ``name`` column is the membership (the join key for matching components
across two projects), and ``x,y,z`` are the solved positions the scale oracle
compares against the nav.

The exit code proves nothing (an export can succeed and write nothing, or
write another layout), so success here means: one CSV per name, each
opening with ``#cameras N`` and holding exactly N camera rows.

Usage:
    python -m modules.export_registrations --project P.rsproj --out DIR
        --names names.txt [--flight-log LOG | --crs epsg:NNNNN] [--log_dir D]
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from module_base.settings_store import SettingsStore, realityscan_env  # noqa: E402
from modules.export_deliverables import read_component_names  # noqa: E402
from modules.flight_logs import crs_for_flight_log  # noqa: E402
from modules.realityscan_interface.realityscan_cli import RealityScanCLI  # noqa: E402


def read_registration_csv(path: str) -> dict:
    """Parse one RUMI registration CSV.

    Returns ``{'declared': N, 'cameras': [(name, x, y, z), ...]}`` where
    ``declared`` is the header's camera count. Rows whose position does not
    parse keep ``None`` coordinates rather than vanishing, so the row count
    can still be checked against the header.
    """
    declared = None
    cameras: list[tuple] = []
    with open(path, encoding='utf-8-sig', errors='replace') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            if line.startswith('#'):
                if declared is None and line.lower().startswith('#cameras'):
                    try:
                        declared = int(line.split()[1])
                    except (IndexError, ValueError):
                        declared = None
                continue
            parts = line.split(',')
            try:
                xyz = tuple(float(v) for v in parts[1:4])
            except (ValueError, IndexError):
                xyz = (None, None, None)
            if len(xyz) != 3:
                xyz = (None, None, None)
            cameras.append((parts[0].strip(), *xyz))
    return {'declared': declared, 'cameras': cameras}


def census(out_dir: str, names: list[str]) -> list[str]:
    """Problems with the exported CSVs, one line each; empty = complete."""
    problems = []
    for name in names:
        path = os.path.join(out_dir, name + '.csv')
        if not os.path.isfile(path):
            problems.append(f'{name}: no CSV')
            continue
        rec = read_registration_csv(path)
        if rec['declared'] is None:
            problems.append(f'{name}: no "#cameras N" header - wrong format')
        elif rec['declared'] != len(rec['cameras']):
            problems.append(f"{name}: header declares {rec['declared']} "
                            f"cameras, file holds {len(rec['cameras'])}")
        elif rec['declared'] == 0:
            problems.append(f'{name}: zero cameras')
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--project', required=True, help='.rsproj to read')
    parser.add_argument('--out', required=True,
                        help='output directory, one <name>.csv per component')
    parser.add_argument('--names', required=True,
                        help='component-name list file, one name per line')
    parser.add_argument('--log_dir', default=None,
                        help='driver log directory (default: <out>/logs)')
    parser.add_argument('--flight-log', default=None,
                        help='zone-tagged flight log whose UTM zone becomes '
                             'the coordinate system the positions are '
                             'written in; overrides --crs')
    parser.add_argument('--crs', default=None,
                        help='coordinate system as authority:id')
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    logger = logging.getLogger('export_registrations')

    if not os.path.isfile(args.project):
        logger.error('project not found: %r', args.project)
        return 1
    try:
        names = read_component_names(args.names)
    except OSError as exc:
        logger.error('cannot read component name list %r: %s', args.names, exc)
        return 1
    if not names:
        logger.error('component name list %r names NOTHING', args.names)
        return 1

    crs = args.crs or os.environ.get('RS_PROJECT_CRS')
    if args.flight_log:
        derived = crs_for_flight_log(args.flight_log)
        if not derived:
            logger.error('--flight-log %r carries no UTM zone tag',
                         args.flight_log)
            return 1
        crs = derived.lower()
    if crs:
        os.environ['RS_PROJECT_CRS'] = crs
        logger.info('positions written in %s', crs)
    else:
        logger.warning('no --crs / --flight-log and RS_PROJECT_CRS unset: '
                       'positions come out in whatever coordinate system the '
                       'application last held')

    settings = SettingsStore()
    if not os.environ.get('RS_INSTANCE'):
        settings.ask('realityscan', 'instance_name', None, 'RS1')
    if not os.environ.get('RS_CACHE_DIR'):
        settings.ask('realityscan', 'cache_dir', None, '')
    os.environ.update(realityscan_env(settings))

    log_dir = args.log_dir or os.path.join(args.out, 'logs')
    logger.info('exporting registration for %d component(s)', len(names))
    cli = RealityScanCLI(logger, settings)
    result = cli.run_batch_script(
        'ExportRegistrations.bat',
        [str(args.project), str(args.out), str(args.names)], log_dir)
    if not result.success:
        logger.error('registration export FAILED (exit %s, %s). Log: %s',
                     result.return_code, result.errors or '<no detail>',
                     result.log_path)
        return 1
    problems = census(args.out, names)
    if problems:
        logger.error('workflow returned success but %d of %d CSVs are not '
                     'usable: %s', len(problems), len(names),
                     '; '.join(problems[:12]))
        return 1
    logger.info('registration export complete: %d CSVs in %s (%.1f min)',
                len(names), args.out, result.duration_seconds / 60)
    return 0


if __name__ == '__main__':
    sys.exit(main())
