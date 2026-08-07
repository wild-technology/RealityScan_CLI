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
from modules.realityscan_interface.realityscan_cli import RealityScanCLI  # noqa: E402


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
        logger.info('export deliverables succeeded in %.1f min. '
                    'Deliverables in %s. Log: %s',
                    result.duration_seconds / 60, args.exports,
                    result.log_path)
        return 0
    logger.error('export deliverables FAILED (exit %s, %s). Log: %s',
                 result.return_code, result.errors or '<no error detail>',
                 result.log_path)
    return 1


if __name__ == '__main__':
    sys.exit(main())
