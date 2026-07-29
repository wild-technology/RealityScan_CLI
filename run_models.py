#!/usr/bin/env python3
"""Model every final component of a workspace's assembly, scale-gated.

The workspace-generic successor to the H2024 drivers: reads the latest
merge_report.json for the final components, resolves each one's metric scale
(stem-oracle verdicts from the report where present; the correspondence-free
quantile-ratio oracle for fused components whose ordinal sidecars defeat stem
pairing - B10), then runs GenerateModel.bat per PASSING component,
smallest-first (cost ladder: the recipe proves itself on a cheap component
before the big one spends hours). Ends with ONE dated RC_projects copy via
SaveProjectCopy.bat - per-component dated copies stay deferred
(owner 2026-07-28: saving with intermediates live is inordinate).

Resumable: components already reported successful in models_report.json are
skipped.

Usage:
    py -3.13 run_models.py --workspace F:/na156_h2024_v2 [--force]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

from modules import scale_oracle  # noqa: E402
from modules.realityscan_interface.realityscan_cli import RealityScanCLI  # noqa: E402
from wildscan.workspace import Workspace  # noqa: E402

MIN_FREE_GB = 50.0


def resolve_scale(key: str, comp: dict, report: dict,
                  workspace: Workspace, union_log: str,
                  logger: logging.Logger) -> tuple[str, str, float | None]:
    """(status, why, median) - stem verdict from the report, else the
    quantile oracle on the component's own harvest."""
    verdict = report.get('input_scales', {}).get(key)
    if verdict and verdict.get('status') != 'unmeasured':
        return (verdict['status'], verdict.get('explanation', ''),
                verdict.get('median'))
    rsalign = comp.get('rsalign', '')
    manifest_path = rsalign + '.manifest.json'
    identity = os.path.join(os.path.dirname(rsalign), 'identity_r0')
    if not (os.path.isfile(manifest_path) and os.path.isdir(identity)):
        return 'unmeasured', 'no manifest or harvest beside the export', None
    with open(manifest_path, encoding='utf-8') as fh:
        manifest = json.load(fh)
    solved = scale_oracle.solved_position_cloud(identity)
    members = scale_oracle.member_multiset(
        manifest, str(workspace.aligned))
    nav = scale_oracle.nav_position_multiset(union_log, members)
    stats = scale_oracle.quantile_ratio_scale(solved, nav)
    status, why = scale_oracle.verdict(stats)
    return status, f'{why} (quantile-ratio)', (
        None if stats is None else stats['median'])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--force', action='store_true',
                        help='re-model components already reported successful')
    args = parser.parse_args()

    ws = Workspace(args.workspace)
    logging.basicConfig(
        level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
        handlers=[logging.FileHandler(ws.root / 'models_driver.log',
                                      encoding='utf-8'),
                  logging.StreamHandler(sys.stdout)])
    logger = logging.getLogger('run_models')

    merge = ws.latest_merge()
    project = ws.assembly_project()
    if not merge or not project:
        logger.error('no merge report / assembly project under %s', ws.root)
        return 1
    with open(merge / 'merge_report.json', encoding='utf-8') as fh:
        report = json.load(fh)
    union_logs = sorted((merge).glob('flight_log*_UTM.txt')) + \
        sorted((merge / 'assembly').glob('flight_log*_UTM.txt'))
    if not union_logs:
        logger.error('no union flight log beside the merge report')
        return 1
    union_log = str(union_logs[0])

    report_path = ws.root / 'models_report.json'
    out: dict = {'started': time.strftime('%Y-%m-%d %H:%M:%S'),
                 'project': str(project), 'models': []}
    already: set[str] = set()
    if report_path.is_file() and not args.force:
        with open(report_path, encoding='utf-8') as fh:
            prior = json.load(fh)
        out['models'] = [m for m in prior.get('models', [])
                         if m.get('success')]
        already = {m['component'] for m in out['models']}

    def flush() -> None:
        with open(report_path, 'w', encoding='utf-8') as fh:
            json.dump(out, fh, indent=2)

    finals = [(c.get('key', '?'), c)
              for rec in report.get('clusters', [])
              for c in rec.get('final_components', [])]
    finals.sort(key=lambda kc: kc[1].get('camera_count') or 0)

    os.environ.setdefault('RS_INSTANCE', 'RS1')
    os.environ.setdefault('RS_CACHE_DIR', r'E:\rscache')
    os.environ.setdefault('RS_HEADLESS', '0')
    os.environ.pop('RS_PROJECTS_DIR', None)   # dated copies deferred
    os.environ.pop('RS_PROJECT_LABEL', None)
    cli = RealityScanCLI(logging.getLogger('models'))
    logs_dir = str(ws.root / 'logs')

    for key, comp in finals:
        name = key.split('/')[-1]
        if name in already:
            logger.info('%s: already modelled - skipping', name)
            continue
        status, why, median = resolve_scale(key, comp, report, ws,
                                            union_log, logger)
        entry = {'component': name, 'cameras': comp.get('camera_count'),
                 'scale': median, 'status': status, 'why': why}
        if status != 'pass':
            logger.error('SCALE GATE: %s not modelled (%s - %s)',
                         name, status, why)
            entry['skipped'] = 'scale_gate'
            out['models'].append(entry)
            flush()
            continue
        if shutil.disk_usage(ws.root.drive + '\\').free / 1024**3 < MIN_FREE_GB:
            logger.error('ABORT: below the %.0f GB floor', MIN_FREE_GB)
            entry['skipped'] = 'disk_floor'
            out['models'].append(entry)
            flush()
            break
        logger.info('=== model %s (%s cams, scale %s) ===',
                    name, entry['cameras'], median)
        started = time.time()
        res = cli.run_batch_script('GenerateModel.bat',
                                   [str(project), name], logs_dir)
        entry.update(success=res.success, errors=res.errors,
                     duration_min=round((time.time() - started) / 60, 1))
        out['models'].append(entry)
        flush()
        logger.info('model %s: success=%s in %.1f min', name, res.success,
                    entry['duration_min'])
        if not res.success:
            logger.error('model %s FAILED - stopping so evidence survives',
                         name)
            break

    done = [m for m in out['models'] if m.get('success')]
    if done:
        import merge_zones
        merge_zones.set_project_save_env(str(ws.batched), ws.root.name.upper())
        dated = os.path.join(
            os.environ['RS_PROJECTS_DIR'],
            f'{ws.root.name.upper()}_merged_'
            f'{os.environ["RS_PROJECT_DATE"]}.rsproj')
        logger.info('project complete - single dated copy -> %s', dated)
        res = cli.run_batch_script('SaveProjectCopy.bat',
                                   [str(project), dated], logs_dir)
        out['dated_copy'] = {'path': dated, 'success': res.success}
        flush()

    logger.info('DONE: %d model(s). Report: %s', len(done), report_path)
    return 0 if done else 1


if __name__ == '__main__':
    sys.exit(main())
