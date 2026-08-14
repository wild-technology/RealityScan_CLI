#!/usr/bin/env python3
"""Export the per-component deliverables of a finished, modelled assembly.

Thin driver over ``ExportDeliverables.bat``, which does the real work in
ONE RealityScan session (per component named in the list file:
OBJ_NiraParts, FBX_Parts, dense colored PLY). The deliverable pinning
lives entirely in the .bat and its Metadata presets
(ModelExportParamsOBJ_NiraParts / ModelExportParamsFBX_Parts /
ModelExportParamsPLY_DensePoints) - this driver adds nothing to them.

It exists so the export stage goes through
``RealityScanCLI.run_batch_script`` like every other RealityScan
invocation (hard rule 1): per-instance lock, marker-file hygiene, progress
tailing and stall warnings, resource trace, and verified instance
shutdown. The wildscan portal previously ran the .bat via a raw
``["cmd", "/c", ...]`` Popen, which provided none of that, broke on
space-containing checkout paths (cmd strips the outer quotes -
run_batch_script's own comment), and - because the portal runner captures
stdout in a PIPE - let the ``start ""``-launched RealityScan GUI child
inherit that pipe (WINDOWS TRAP recorded 2026-08-07). run_batch_script
hands the .bat a log FILE instead, so the boot path stays detached.

Layering note: this module is imported by wildscan (and importable by any
driver) but imports only module_base + modules code itself - never
wildscan. The stage passes the workspace-derived paths as arguments.

Usage:
    py -3.13 modules/export_deliverables.py
        --project D:/dive/final_assembly/assembly/Assembly.rsproj
        --exports D:/dive/exports
        --names   D:/dive/exports/components.names
        [--log_dir D:/dive/logs]
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
from modules.flight_logs import crs_for_flight_log  # noqa: E402
from modules.realityscan_interface.realityscan_cli import RealityScanCLI  # noqa: E402


# Per component, ExportDeliverables.bat writes one subfolder per format.
EXPORT_KINDS = ('obj', 'fbx', 'ply')


def read_component_names(names_file: str) -> list[str]:
    """Non-blank component names from the list file, BOM-tolerant."""
    with open(names_file, encoding='utf-8-sig') as fh:
        return [line.strip() for line in fh if line.strip()]


def missing_exports(exports_dir: str, names: list[str]) -> list[str]:
    """'<component>/<kind>' entries that hold no non-empty file.

    The .bat's per-component loop runs zero iterations on an empty name
    list, falls through to -quit and exits 0; and a selection-driven
    export under -silent can auto-answer the "Export Selection" dialog and
    export NOTHING while still succeeding (MergeZoneComponents.bat records
    the census reading 0). Exit code plus an empty errors marker is
    therefore not evidence a deliverable exists (audit 2026-08-07).
    """
    missing = []
    for name in names:
        for kind in EXPORT_KINDS:
            kind_dir = os.path.join(exports_dir, name, kind)
            try:
                produced = any(
                    os.path.getsize(os.path.join(kind_dir, f)) > 0
                    for f in os.listdir(kind_dir)
                    if os.path.isfile(os.path.join(kind_dir, f)))
            except OSError:
                produced = False
            if not produced:
                missing.append(f'{name}/{kind}')
    return missing


def run_export(project: str, exports_dir: str, names_file: str,
               log_dir: str = None, logger: logging.Logger = None,
               settings: SettingsStore = None):
    """Run ExportDeliverables.bat through the unified execution layer.

    Same argument contract as the .bat itself (%1 .rsproj project path,
    %2 output directory, %3 component-name list file - one name per
    line). ``log_dir`` defaults to ``<exports parent>/logs``, which for a
    workspace's ``exports/`` folder is the workspace ``logs/`` directory
    every other stage driver writes to. Returns the ``WorkflowResult``.
    """
    logger = logger or logging.getLogger('export_deliverables')
    settings = settings or SettingsStore()
    # Machine constants from the single source of truth (RS_INSTANCE /
    # RS_HEADLESS / RS_CACHE_DIR). Environment wins over stored values, so
    # a portal/driver that already exported RS_* is passed through
    # unchanged and this update is a no-op for it.
    os.environ.update(realityscan_env(settings))
    if log_dir is None:
        log_dir = os.path.join(
            os.path.dirname(os.path.abspath(exports_dir)) or '.', 'logs')
    cli = RealityScanCLI(logger, settings)
    return cli.run_batch_script(
        'ExportDeliverables.bat',
        [str(project), str(exports_dir), str(names_file)], str(log_dir))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--project', required=True,
                        help='.rsproj assembly project path')
    parser.add_argument('--exports', required=True,
                        help='output directory (per-component subfolders '
                             'are created by the workflow)')
    parser.add_argument('--names', required=True,
                        help='component-name list file, one name per line')
    parser.add_argument('--log_dir', default=None,
                        help='driver log directory '
                             '(default: <exports parent>/logs)')
    parser.add_argument('--flight-log', default=None,
                        help='zone-tagged flight log whose UTM zone becomes '
                             'the export CRS; overrides --crs')
    parser.add_argument('--crs', default=None,
                        help='output coordinate system as authority:id '
                             '(e.g. epsg:32653). Without one the export '
                             'inherits whatever CRS the app last held')
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    logger = logging.getLogger('export_deliverables')

    # Fail fast, before an instance boots: the .bat checks these too, but
    # by then a RealityScan session is already the cost of the message.
    if not os.path.isfile(args.project):
        logger.error('assembly project not found: %r - has the '
                     'merge/model stage produced one?', args.project)
        return 1
    if not os.path.isfile(args.names):
        logger.error('component name list not found: %r', args.names)
        return 1
    # An EMPTY (or whitespace-only) list makes the .bat's `for /f` loop run
    # ZERO iterations, -quit, and exit 0: a no-op that reports success and
    # produces no deliverables at all (audit 2026-08-07).
    try:
        names = read_component_names(args.names)
    except OSError as exc:
        logger.error('cannot read component name list %r: %s', args.names, exc)
        return 1
    if not names:
        logger.error('component name list %r names NOTHING - the export '
                     'workflow would boot RealityScan, export zero '
                     'components and exit 0. Populate it from the merge '
                     "report's final_components first.", args.names)
        return 1
    logger.info('exporting %d component(s): %s', len(names), ', '.join(names))

    # Output CRS. The exports are raw metric coordinates; the coordinate
    # SYSTEM they are stamped with comes from the application, and nothing
    # here ever set it - H2077 (a 53N cruise) exported as
    # "epsg:32757 - UTM zone 57S", the stale FlightLogParams placeholder
    # zone (2026-08-14). write_flight_log_params only governs the CRS of
    # the flight log being IMPORTED, never the export.
    crs = args.crs
    if args.flight_log:
        derived = crs_for_flight_log(args.flight_log)
        if derived:
            crs = derived.lower()
        else:
            logger.error('--flight-log %r carries no UTM zone tag, so no '
                         'export CRS could be derived from it',
                         args.flight_log)
            return 1
    if crs:
        os.environ['RS_OUTPUT_CRS'] = crs
        logger.info('export coordinate system: %s', crs)
    else:
        os.environ.pop('RS_OUTPUT_CRS', None)
        logger.warning(
            'No export CRS given (--crs / --flight-log). The models will be '
            'stamped with whatever coordinate system the application last '
            'held, which is NOT necessarily this cruise - pass one.')

    # Prompt-with-default on a TTY, silent stored/fallback when unattended
    # (SettingsStore.ask); values already in the environment are never
    # prompted for or demoted (same pattern as run_models.py).
    settings = SettingsStore()
    if not os.environ.get('RS_INSTANCE'):
        settings.ask('realityscan', 'instance_name', None, 'RS1')
    if not os.environ.get('RS_CACHE_DIR'):
        settings.ask('realityscan', 'cache_dir', None, '')

    result = run_export(args.project, args.exports, args.names,
                        log_dir=args.log_dir, logger=logger,
                        settings=settings)
    if result.success:
        missing = missing_exports(args.exports, names)
        if missing:
            logger.error(
                'export workflow returned success but %d of %d expected '
                'deliverable folder(s) hold no file: %s. RealityScan reports '
                'success for do-nothing exports (a selection-driven export '
                'under -silent can export NOTHING), so the exit code alone '
                'proves nothing. Log: %s',
                len(missing), len(names) * len(EXPORT_KINDS),
                ', '.join(missing[:12]) + (' ...' if len(missing) > 12 else ''),
                result.log_path)
            return 1
        logger.info('export deliverables succeeded in %.1f min. '
                    '%d component(s) exported to %s. Log: %s',
                    result.duration_seconds / 60, len(names), args.exports,
                    result.log_path)
        return 0
    logger.error('export deliverables FAILED (exit %s, %s). Log: %s',
                 result.return_code, result.errors or '<no error detail>',
                 result.log_path)
    return 1


if __name__ == '__main__':
    sys.exit(main())
