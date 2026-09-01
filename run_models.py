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

Direct mode (--project) drives GenerateModel.bat against an explicit
on-disk .rsproj instead of a merge-report workspace - for scenes built
outside the merge pipeline (GUI reconstructions, probes, re-models).
GenerateModel.bat's contract: %1 scene path, %2 component name (empty =
maximal component), %3 large-triangle threshold (default 30). Direct mode
BYPASSES the scale gate (there is no merge report to gate on) - the
operator vouches for the scene. RS_PROJECTS_DIR/RS_PROJECT_LABEL are left
untouched in direct mode, so an operator who exports them gets the .bat's
dated-copy saves; workspace mode still defers dated copies to its single
end-of-run copy.

Usage:
    py -3.13 run_models.py --workspace F:/na156_h2024_v2 [--force]
    py -3.13 run_models.py --project D:/scene/Assembly.rsproj \
                           [--component zone_1_c0] [--large_tri_threshold 30]
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

from module_base.settings_store import SettingsStore, realityscan_env  # noqa: E402
from modules import scale_oracle  # noqa: E402
from modules.realityscan_interface.realityscan_cli import RealityScanCLI  # noqa: E402
from modules.workspace_census import Workspace, _records  # noqa: E402

MIN_FREE_GB = 50.0


def project_size_gb(project) -> float:
    """Size of a .rsproj plus its sibling data directory, in GB.

    RealityScan keeps the bulk beside the .rsproj in a folder of the same
    stem, so the .rsproj alone is ~1 MB and tells you nothing about what a
    copy costs. Used to decide whether a dated copy can be afforded.
    """
    project = Path(project)
    total = project.stat().st_size if project.is_file() else 0
    data_dir = project.with_suffix('')
    if data_dir.is_dir():
        for f in data_dir.rglob('*'):
            try:
                if f.is_file():
                    total += f.stat().st_size
            except OSError:
                pass
    return total / 1024 ** 3


def scale_gate_enabled(report: dict) -> bool:
    """Whether this workspace's merge report asks for the scale gate to REFUSE.

    merge_zones records the operator's --scale_gate answer as
    ``{"scale_gate": {"enabled": bool, ...}}``. Workspace modelling used to
    gate unconditionally and ignore it, so a workspace deliberately assembled
    with --scale_gate false still had its out-of-band components refused.

    Absent or malformed = True: an old report predating the field must keep
    gating, because silently MODELLING something a previous run refused is the
    worse failure of the two.
    """
    gate = report.get('scale_gate')
    if not isinstance(gate, dict):
        return True
    value = gate.get('enabled', True)
    return bool(value) if isinstance(value, bool) else True


def make_cli(logger_name: str = 'models') -> RealityScanCLI:
    """Machine constants from the settings store's 'realityscan' section -
    prompt-with-default on a TTY, silent stored/fallback when unattended
    (SettingsStore.ask). Values already in the environment win, exactly
    as the old setdefault calls allowed: wildscan and other callers pass
    explicit RS_* values, and those are never prompted for or demoted."""
    settings = SettingsStore()
    if not os.environ.get('RS_INSTANCE'):
        settings.ask('realityscan', 'instance_name', None, 'RS1')
    if not os.environ.get('RS_CACHE_DIR'):
        settings.ask('realityscan', 'cache_dir', None, '')
    os.environ.update(realityscan_env(settings))
    return RealityScanCLI(logging.getLogger(logger_name), settings)


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


def run_direct(args: argparse.Namespace) -> int:
    """Direct mode: GenerateModel.bat against an explicit .rsproj.

    No merge report exists, so the scale gate CANNOT run - stated loudly
    rather than silently skipped. One component per invocation (the .bat
    models one component per boot); the outcome is appended to
    models_report.json beside the project so repeat invocations build the
    same evidence trail workspace mode keeps."""
    project = Path(args.project).resolve()
    # Validate BEFORE the FileHandler: a mistyped --project whose parent
    # does not exist must produce this message, not a FileNotFoundError
    # traceback out of basicConfig (clean-sweep 2026-08-07).
    if not project.is_file():
        print(f'ERROR: project not found: {project}', file=sys.stderr)
        return 1
    logging.basicConfig(
        level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
        handlers=[logging.FileHandler(project.parent / 'models_driver.log',
                                      encoding='utf-8'),
                  logging.StreamHandler(sys.stdout)])
    logger = logging.getLogger('run_models')
    if shutil.disk_usage(project.parent).free / 1024**3 < MIN_FREE_GB:
        logger.error('ABORT: below the %.0f GB floor', MIN_FREE_GB)
        return 1
    logger.warning('direct mode: no merge report, so the metric-scale gate '
                   'does NOT run - the operator vouches for %s', project.name)

    cli = make_cli()
    logs_dir = str(project.parent / 'logs')
    name = args.component or 'maximal'
    bat_args = [str(project), args.component]
    if args.large_tri_threshold is not None:
        bat_args.append(str(args.large_tri_threshold))

    logger.info('=== model %s in %s ===', name, project.name)
    started = time.time()
    res = cli.run_batch_script('GenerateModel.bat', bat_args, logs_dir)
    entry = {'mode': 'direct', 'project': str(project), 'component': name,
             'success': res.success, 'errors': res.errors,
             'duration_min': round((time.time() - started) / 60, 1),
             'finished': time.strftime('%Y-%m-%d %H:%M:%S')}

    report_path = project.parent / 'models_report.json'
    out: dict = {'models': []}
    if report_path.is_file():
        try:
            with open(report_path, encoding='utf-8') as fh:
                out = json.load(fh)
        except ValueError:
            logger.warning('unreadable %s - starting a fresh report',
                           report_path)
            out = {'models': []}
    out.setdefault('models', []).append(entry)
    with open(report_path, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, indent=2)
    logger.info('model %s: success=%s in %.1f min - report: %s',
                name, res.success, entry['duration_min'], report_path)
    return 0 if res.success else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--workspace',
                      help='workspace root carrying a merge report '
                           '(default mode: scale-gated, smallest-first, '
                           'resumable)')
    mode.add_argument('--project',
                      help='direct mode: explicit on-disk .rsproj for '
                           'GenerateModel.bat - no merge report needed, '
                           'scale gate BYPASSED')
    parser.add_argument('--component', default='',
                        help="direct mode: component name to model "
                             "(default '' = maximal component, "
                             "GenerateModel.bat's own fallback)")
    parser.add_argument('--large_tri_threshold', type=int, default=None,
                        help='direct mode: large-triangle threshold, '
                             'GenerateModel.bat arg 3 (its default: 30)')
    parser.add_argument('--force', action='store_true',
                        help='workspace mode: re-model components already '
                             'reported successful')
    args = parser.parse_args()

    if not args.project and (args.component
                             or args.large_tri_threshold is not None):
        parser.error('--component/--large_tri_threshold only apply to '
                     '--project (direct mode)')
    if args.project:
        return run_direct(args)

    ws = Workspace(args.workspace)
    # Validate BEFORE the FileHandler, exactly as run_direct does: a
    # mistyped --workspace (or one naming a FILE) used to die with a
    # FileNotFoundError traceback out of basicConfig trying to open
    # <workspace>/models_driver.log (audit 2026-08-07).
    if not ws.root.is_dir():
        print(f'ERROR: workspace not found (or not a directory): {ws.root}',
              file=sys.stderr)
        return 1
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

    # _records drops anything that is not a dict record: a merge report
    # whose 'clusters' is a dict (or holds strings) used to crash here with
    # AttributeError instead of a message (audit 2026-08-07).
    finals = [(c.get('key', '?'), c)
              for rec in _records(report, 'clusters')
              for c in _records(rec, 'final_components')]
    if not finals:
        logger.error('merge report %s declares no final components - nothing '
                     'to model', merge / 'merge_report.json')
        return 1
    finals.sort(key=lambda kc: kc[1].get('camera_count') or 0)

    cli = make_cli()
    os.environ.pop('RS_PROJECTS_DIR', None)   # dated copies deferred
    os.environ.pop('RS_PROJECT_LABEL', None)
    logs_dir = str(ws.root / 'logs')
    disk_floor_hit = False

    for key, comp in finals:
        name = key.split('/')[-1]
        if name in already:
            logger.info('%s: already modelled - skipping', name)
            continue
        status, why, median = resolve_scale(key, comp, report, ws,
                                            union_log, logger)
        entry = {'component': name, 'cameras': comp.get('camera_count'),
                 'scale': median, 'status': status, 'why': why}
        # merge_zones records the operator's --scale_gate answer in the report;
        # this loop used to ignore it and gate unconditionally, so a workspace
        # deliberately assembled with --scale_gate false still had its
        # out-of-band components refused here. The measured scale is kept in
        # the entry either way - disabling the gate stops it REFUSING, it does
        # not stop it MEASURING.
        gate_enabled = scale_gate_enabled(report)
        if status != 'pass' and not gate_enabled:
            logger.warning(
                'scale gate DISABLED for this workspace: modelling %s anyway '
                '(%s - %s). Its measured scale is recorded, not corrected.',
                name, status, why)
            entry['scale_gate_bypassed'] = True
        elif status != 'pass':
            logger.error('SCALE GATE: %s not modelled (%s - %s)',
                         name, status, why)
            entry['skipped'] = 'scale_gate'
            out['models'].append(entry)
            flush()
            continue
        # The resolved path, not a reconstructed drive root: Path('ws').drive
        # is '' for a relative --workspace, so `drive + '\\'` became '\\'
        # and the floor measured the SYSTEM drive instead of the data
        # volume (audit 2026-08-07).
        if shutil.disk_usage(ws.root).free / 1024**3 < MIN_FREE_GB:
            logger.error('ABORT: below the %.0f GB floor', MIN_FREE_GB)
            entry['skipped'] = 'disk_floor'
            out['models'].append(entry)
            flush()
            disk_floor_hit = True
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
    # A dated copy duplicates the WHOLE project. Writing one immediately after
    # aborting for low disk is self-defeating, and it filled the volume for
    # real on NA165/H2060 (2026-09-01): the loop stopped at 32 GB free, then
    # SaveProjectCopy tried to write a 31.8 GB duplicate, hit 0 bytes free and
    # died with 0x80070070 ERROR_DISK_FULL, leaving a partial copy that itself
    # had to be deleted to recover the machine. The in-place project is
    # already saved by GenerateModel; the dated copy is a convenience.
    free_gb_now = shutil.disk_usage(ws.root).free / 1024**3
    if done and disk_floor_hit:
        logger.error(
            'SKIPPING the dated project copy: this run aborted on the %.0f GB '
            'disk floor (%.1f GB free now). Copying the whole project here is '
            'what fills the volume. Free space, then rerun to get the copy.',
            MIN_FREE_GB, free_gb_now)
        out['dated_copy'] = {'skipped': 'disk_floor', 'free_gb': round(free_gb_now, 1)}
        flush()
    elif done and free_gb_now < MIN_FREE_GB * 2:
        logger.error(
            'SKIPPING the dated project copy: only %.1f GB free and a copy '
            'duplicates the entire project. Free space, then rerun.',
            free_gb_now)
        out['dated_copy'] = {'skipped': 'low_disk', 'free_gb': round(free_gb_now, 1)}
        flush()
    elif done and project_size_gb(project) + MIN_FREE_GB > free_gb_now:
        # A fixed threshold is not enough: it only asks "is there room to
        # start", not "is there room to FINISH". On NA165/H2060 the run had
        # 157 GB free - comfortably past 2x the floor - and wrote a 119.5 GB
        # duplicate, leaving 43 GB and starving the export that came next.
        # Size the check on the actual project instead.
        size_gb = project_size_gb(project)
        logger.error(
            'SKIPPING the dated project copy: the project is %.1f GB and only '
            '%.1f GB is free, which would leave under the %.0f GB floor. A '
            'copy that fits but strands the next stage is not worth it.',
            size_gb, free_gb_now, MIN_FREE_GB)
        out['dated_copy'] = {'skipped': 'would_breach_floor',
                             'project_gb': round(size_gb, 1),
                             'free_gb': round(free_gb_now, 1)}
        flush()
    elif done:
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
