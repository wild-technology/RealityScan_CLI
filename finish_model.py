#!/usr/bin/env python3
"""Finish an already-computed model into final deliverables (attach-only).

Drives ModelToFinal.bat against a RealityScan instance that is ALREADY
running with the scene loaded: texture -> [simplify] -> unwrap ->
reproject -> export -> save. It never calculates a mesh and never creates
a scene.

SAFETY PROPERTY - attach-only, scene never reset:
    This driver goes through RealityScanCLI.run_attach_script, which
    refuses to run unless ``-getStatus`` answers for the target instance,
    performs no shutdown before or after, and clears no marker files. It
    NEVER calls startRealityScan.bat: that boot script's already-running
    branch issues ``-newScene -deleteAutosave``, which destroys the live
    scene. That is exactly the incident the ON2026 delivery had to dodge
    (HANDOFF.md, 2026-08-07): the ON2026 mesh was reconstructed
    interactively over ~9 h in a GUI session, and every boot-path workflow
    would have reset it - ModelToFinal.bat attaches instead, and this
    driver preserves that property end to end.

The per-operation error gate lives in ModelToFinal.bat's :run subroutine
(rev/lastError baselining via -getStatus), because a GUI-launched instance
never writes errors_<instance>.txt.

Usage:
    py -3.13 finish_model.py --outdir "M:/.../final" [--instance RS1]
        [--name Final] [--preset 4x8k] [--simplify true]
        [--format objmetric] [--save-path "M:/.../final/scene.rsproj"]

``--instance`` defaults to ``*`` ("first available") - fine for a single
interactive session, ambiguous with two instances running: name one
explicitly in that case.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

REPO = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, REPO)

from module_base.settings_store import SettingsStore, realityscan_env  # noqa: E402
from modules.realityscan_interface.realityscan_cli import RealityScanCLI  # noqa: E402

TEXTURE_PRESETS = ('highpoly', '8k', '4x8k', '16k', 'fixed100', 'fixed50')
EXPORT_FORMATS = ('obj', 'objmetric', 'fbx', 'glb', 'none')


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--instance', default='*',
                        help='target instance name, or * for "first '
                             'available" (single running instance only)')
    parser.add_argument('--outdir', required=True,
                        help='directory the final model files are exported to')
    parser.add_argument('--name', default='Final',
                        help='base name for the exported model')
    parser.add_argument('--preset', default='4x8k', choices=TEXTURE_PRESETS,
                        help='texture preset (4x8k = the owner 8K cap)')
    parser.add_argument('--simplify', default='true',
                        choices=('true', 'false'),
                        help='run the four simplify/clean passes')
    parser.add_argument('--format', default='objmetric',
                        choices=EXPORT_FORMATS,
                        help='export format (objmetric = OBJ at true scale '
                             '1.0 for survey/GIS; obj = scale 100 Unreal)')
    parser.add_argument('--save-path', default=None,
                        help='explicit .rsproj path for the final -save; '
                             'omit to save to the project\'s original '
                             'location (a never-saved GUI scene has none - '
                             'prefer an explicit path there)')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    logger = logging.getLogger('finish_model')

    # Machine constants from the single source of truth (RS_INSTANCE /
    # RS_HEADLESS / RS_CACHE_DIR; environment wins over stored values).
    # Attach mode never boots, so these matter only for the script's
    # own-vs-foreign marker gate (RS_INSTANCE) - but resolving them the
    # one blessed way keeps every driver identical.
    settings = SettingsStore()
    os.environ.update(realityscan_env(settings))

    outdir = os.path.abspath(args.outdir)
    settings.set('finish_model', 'outdir', outdir)

    if args.save_path:
        # RS_SAVE_PATH is an env var, not a positional arg: cmd only
        # exposes %1-%9 and a path must never ride argument splitting.
        os.environ['RS_SAVE_PATH'] = os.path.abspath(args.save_path)

    cli = RealityScanCLI(logger, settings)
    logs_dir = os.path.join(outdir, 'logs')

    # ModelToFinal.bat positional contract (run_attach_script injects the
    # instance as %1): %2 export dir, %3 name, %4 texture preset,
    # %5 simplify, %6 format. %7 cull / %8 correct colors / %9 source
    # model keep their in-script defaults (false/false/selected model).
    result = cli.run_attach_script(
        'ModelToFinal.bat',
        [outdir, args.name, args.preset, args.simplify, args.format],
        logs_dir, instance=args.instance)

    if result.success:
        logger.info('ModelToFinal succeeded in %.1f min. Exports in %s. '
                    'Log: %s', result.duration_seconds / 60, outdir,
                    result.log_path)
        return 0
    logger.error('ModelToFinal FAILED (exit %s, %s). The instance was left '
                 'running and the scene untouched. Log: %s',
                 result.return_code, result.errors or '<no error detail>',
                 result.log_path)
    return 1


if __name__ == '__main__':
    sys.exit(main())
