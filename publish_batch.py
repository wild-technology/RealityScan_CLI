#!/usr/bin/env python3
"""Publish every exported component of a workspace to Cesium ion and/or Nira.

Loops exports/<component>/obj (the format BOTH platforms recommend for
photogrammetry) and drives publish_cesium.py / publish_nira.py per component.
Each destination activates only when its credentials are present, and
--dry-run previews every command without uploading anything:

    Cesium ion   CESIUM_ION_TOKEN env var (assets:write + assets:read)
    Nira         NIRACLIENT_DIR env var -> a configured niraclient checkout
                 (Enterprise plan; run `nira.py configure` once)

Results land in <workspace>/publish_report.json (or --report) so WildScan
can show them. The report is APPENDED to, one record per component per run;
the census judges each component by its newest real record. A --dry-run
writes its preview to <report stem>.dry_run.json instead and leaves the
report itself untouched. Each run's publish_cesium result JSONs (the ion
asset ids) go to <report stem>_results/<run id>/<component>.json.

Usage:
    py -3.13 publish_batch.py --workspace F:/na156_h2024_v2 \
        --prefix "IN-401" [--flight-log <log>] [--dry-run]
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


def resolve_flight_log(workspace: Path) -> Path | None:
    """The workspace's own zone-tagged flight log, or None.

    Searches the merge output (whose union log is what the exported
    components were built against) before raw_images/ and the root, and
    raises SystemExit when zone-tagged logs DISAGREE rather than picking
    one - the same rule flight_logs.find_flight_log applies.
    """
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from modules.flight_logs import assert_one_zone, crs_for_flight_log
    logs = sorted(workspace.glob('*/flight_log*_UTM.txt')) + \
        sorted((workspace / 'raw_images').glob('flight_log*_UTM.txt')) + \
        sorted(workspace.glob('flight_log*_UTM.txt'))
    tagged = [p for p in logs if crs_for_flight_log(str(p))]
    if not tagged:
        return None
    try:
        assert_one_zone([str(p) for p in tagged], str(workspace))
    except ValueError as exc:
        raise SystemExit(f'cannot resolve a flight log: {exc}') from None
    return tagged[0]


def resolve_input_crs(workspace: Path) -> str | None:
    """``'EPSG:32654'`` from the workspace's own flight log, or None.

    Kept as a cross-check only. The CRS that actually places a mesh now
    comes from its ``.rsInfo`` sidecar, which records what the exporter did
    rather than what the flight-log filename implies.
    """
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from modules.flight_logs import crs_for_flight_log
    log = resolve_flight_log(workspace)
    return crs_for_flight_log(str(log)) if log else None


class _Placeholders(dict):
    """format_map dict that leaves unknown {fields} as written."""

    def __missing__(self, key):
        return '{' + key + '}'


def describe(template: str | None, component: str, asset_name: str,
             stem: str) -> str:
    """The ion description for one asset. ``{component}`` is the export
    directory name (e.g. zone_1_c0_L), ``{stem}`` the same without the
    --require-suffix, ``{asset_name}`` the full ion name."""
    if not template:
        return ''
    return template.format_map(_Placeholders(
        component=component, asset_name=asset_name, stem=stem))


def load_report(path: Path) -> dict:
    """The existing report, so a re-run APPENDS instead of erasing it.

    The report used to be rebuilt from scratch on every run and rewritten after
    each component: a resumed run lost the first run's records, including the
    only trace of which components had been published (NA165/H2060's report
    lists 38 of the 39 it published).

    A report that EXISTS but is not a readable {"assets": [...]} is a stop,
    never an empty start: starting over lost every earlier record and, with
    --skip-published, re-published every asset as a duplicate (review
    2026-09-27). Move it aside or repair it."""
    if not path.exists():
        return {'assets': []}
    try:
        with open(path, encoding='utf-8') as fh:
            report = json.load(fh)
    except (OSError, ValueError) as exc:
        raise SystemExit(f'publish report {path} exists but cannot be read '
                         f'({exc}). Refusing to start a new one over it - '
                         'move it aside or repair it.') from None
    if not (isinstance(report, dict) and isinstance(report.get('assets'), list)):
        raise SystemExit(f'publish report {path} is not a publish_batch report '
                         '(no "assets" list). Refusing to overwrite it.')
    return report


def save_report(path: Path, report: dict) -> None:
    """Temp file + os.replace: a kill mid-write leaves the previous report
    whole instead of truncated (which load_report would then refuse)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(report, fh, indent=2)
    os.replace(tmp, path)


def _real_records(report: dict, component: str, asset_name: str, dest: str):
    """Newest-first records of one destination for this component under this
    asset name - not dry runs, not skip markers."""
    for entry in reversed(report.get('assets', [])):
        if entry.get('component') != component \
                or entry.get('asset_name') != asset_name:
            continue
        rec = entry.get(dest)
        if isinstance(rec, dict) and not rec.get('dry_run') \
                and not rec.get('skipped'):
            yield rec


def already_published(report: dict, component: str,
                      asset_name: str) -> dict | None:
    """The newest Cesium record that proves a live, VERIFIED asset under this
    asset name: success, an asset id, tiling COMPLETE and the placement
    verified. Only records written by --result-json carry the id, so a
    report from before 2026-09-27 never qualifies (its components are
    published again - a duplicate, never a gap)."""
    for rec in _real_records(report, component, asset_name, 'cesium'):
        if rec.get('success') and rec.get('asset_id') \
                and rec.get('status') == 'COMPLETE' and rec.get('verified') is True:
            return rec
    return None


def nira_published(report: dict, component: str, asset_name: str) -> dict | None:
    """The newest successful Nira record under this asset name, if any."""
    for rec in _real_records(report, component, asset_name, 'nira'):
        if rec.get('success'):
            return rec
    return None


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
    parser.add_argument('--flight-log', default=None,
                        help='flight log for this cruise. Its nav envelope '
                             'is an independent check on how each mesh is '
                             'placed (default: resolved from the workspace)')
    parser.add_argument('--components', nargs='*', default=None,
                        help='subset of component names (default: all exported)')
    parser.add_argument('--exports', default=None,
                        help='export tree to publish from (default: '
                             '<workspace>/exports). Asset names come from its '
                             'directory names: <prefix> <dir name>')
    parser.add_argument('--report', default=None,
                        help='publish report path (default: '
                             '<workspace>/publish_report.json). Appended to, '
                             'never rebuilt')
    parser.add_argument('--description', default=None,
                        help='ion description per asset; {component}, {stem} '
                             'and {asset_name} are filled in')
    parser.add_argument('--require-suffix', default=None,
                        help='refuse unless EVERY selected directory ends with '
                             'this (e.g. _L) - pointing at the wrong tree must '
                             'not publish the wrong generation')
    parser.add_argument('--skip-published', action='store_true',
                        help='per destination: skip the Cesium upload when the '
                             'report holds a verified, COMPLETE asset id for '
                             'this asset name, and the Nira upload when it '
                             'holds a successful Nira record. Only reports '
                             'written by this version carry the asset id. '
                             'Under --dry-run it says what WOULD be skipped')
    parser.add_argument('--staging-root', default=None,
                        help='stage each component under <root>/<component> '
                             'instead of inside the export tree '
                             '(<dir>/_cesium_local). Must lie outside the '
                             'export tree and not contain it')
    parser.add_argument('--clean-staging', action='store_true',
                        help='forwarded to publish_cesium: remove each '
                             'staging copy after a VERIFIED upload')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    exports = Path(args.exports) if args.exports else \
        Path(args.workspace) / 'exports'
    if not exports.is_dir():
        raise SystemExit(f'no exports directory at {exports}')
    if args.staging_root:
        # publish_cesium EMPTIES each <root>/<component> before staging. A root
        # equal to the export tree, inside it or containing it would put the
        # staging directory on top of an export (review 2026-09-27: every
        # component's obj/fbx/ply deleted, even under --dry-run).
        root, tree = Path(args.staging_root).resolve(), exports.resolve()
        if root.is_relative_to(tree) or tree.is_relative_to(root):
            raise SystemExit(f'--staging-root {root} must lie outside the '
                             f'export tree {tree} and must not contain it')
    report_path = Path(args.report) if args.report else \
        Path(args.workspace) / 'publish_report.json'
    run_id = time.strftime('%Y%m%d-%H%M%S') + f'-{os.getpid()}'
    # One folder per run: a result JSON is never read by a later run, so a
    # publish_cesium that dies before writing its own cannot inherit the
    # previous run's asset id - and no earlier record is ever deleted.
    results_dir = report_path.parent / (report_path.stem + '_results') / run_id

    # publish_cesium now takes the CRS from each mesh's own .rsInfo sidecar,
    # which records what the exporter actually did rather than what a
    # filename implies. The flight log is still worth passing: its nav
    # envelope is an INDEPENDENT check on the transformToModel reading, and
    # a disagreement between the two is exactly the signal we want.
    flight_log = Path(args.flight_log) if args.flight_log else \
        resolve_flight_log(Path(args.workspace))
    if flight_log:
        logger.info('flight log for nav cross-check: %s (%s)',
                    flight_log, resolve_input_crs(Path(args.workspace)))
    else:
        logger.warning(
            'no zone-tagged flight_log*_UTM.txt under %s - publishing without '
            'the independent nav check. Placement will rest on the .rsInfo '
            'sidecar alone. Pass --flight-log to be explicit.', args.workspace)

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

    # The record. A dry run READS it (to say what --skip-published would
    # skip) but writes its preview beside it, never into it: appended
    # previews made the census read "partial" after every preview.
    report = load_report(report_path)
    run_started = time.strftime('%Y-%m-%d %H:%M:%S')
    if args.dry_run:
        out_path = report_path.with_name(report_path.stem + '.dry_run.json')
        out: dict = {'dry_run_of': str(report_path), 'assets': []}
    else:
        out_path, out = report_path, report
    out.setdefault('started', run_started)
    run_record = {'started': run_started, 'exports': str(exports),
                  'dry_run': bool(args.dry_run), 'skipped': []}
    out.setdefault('runs', []).append(run_record)
    comps = sorted(p for p in exports.iterdir()
                   if p.is_dir() and (p / 'obj').is_dir()
                   and any((p / 'obj').iterdir()))
    if args.components:
        wanted = set(args.components)
        comps = [c for c in comps if c.name in wanted]
    if not comps:
        raise SystemExit('no exported obj/ components found')
    if args.require_suffix:
        wrong = [c.name for c in comps if not c.name.endswith(args.require_suffix)]
        if wrong:
            raise SystemExit(
                f'{len(wrong)} selected export dir(s) do not end with '
                f'{args.require_suffix!r} ({", ".join(wrong[:5])}) - is '
                f'{exports} the tree you meant to publish?')

    would = 'WOULD ' if args.dry_run else ''
    this_run: list[dict] = []
    for comp in comps:
        name = f'{args.prefix} {comp.name}'
        entry: dict = {'component': comp.name, 'asset_name': name,
                       'run_started': run_started}
        do_cesium = bool(cesium_token or args.dry_run)
        do_nira = bool(nira_dir or args.dry_run)
        # Skipping is decided PER DESTINATION: a verified Cesium asset must
        # not stop a failed (or never-run) Nira upload from being retried.
        if args.skip_published and do_cesium:
            prior = already_published(report, comp.name, name)
            if prior:
                do_cesium = False
                entry['cesium'] = {'skipped': True, 'asset_id': prior['asset_id']}
                logger.info('%sSKIP Cesium for %s: published and verified as '
                            'asset %s', would, comp.name, prior['asset_id'])
        if args.skip_published and do_nira and nira_published(report, comp.name, name):
            do_nira = False
            entry['nira'] = {'skipped': True}
            logger.info('%sSKIP Nira for %s: already published', would, comp.name)
        if not (do_cesium or do_nira):
            run_record['skipped'].append(comp.name)
            continue
        stem = comp.name[:-len(args.require_suffix)] \
            if args.require_suffix else comp.name
        description = describe(args.description, comp.name, name, stem)
        if do_cesium:
            result_json = results_dir / f'{comp.name}.json'
            argv = [sys.executable, str(REPO / 'publish_cesium.py'),
                    '--name', name, '--dir', str(comp / 'obj'),
                    '--poll', '--verify', '--result-json', str(result_json)]
            if description:
                argv += ['--description', description]
            if flight_log:
                argv += ['--flight-log', str(flight_log)]
            if args.staging_root:
                argv += ['--staging', str(Path(args.staging_root) / comp.name)]
            if args.clean_staging:
                argv.append('--clean-staging')
            if args.dry_run:
                argv.append('--dry-run')
            entry['cesium'] = run(argv, args.dry_run)
            if not args.dry_run:
                try:
                    detail = json.loads(result_json.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    detail = {}
                # Only THIS invocation's record: same asset name, same exit.
                if detail.get('name') == name and \
                        detail.get('exit_code') == entry['cesium'].get('returncode'):
                    for key in ('asset_id', 'url', 'status', 'verified', 'problems'):
                        if key in detail:
                            entry['cesium'][key] = detail[key]
        if do_nira:
            argv = [sys.executable, str(REPO / 'publish_nira.py'),
                    '--name', name, '--dir', str(comp / 'obj'),
                    '--niraclient', nira_dir or '<NIRACLIENT_DIR>']
            if args.dry_run:
                argv.append('--dry-run')
            entry['nira'] = run(argv, args.dry_run)
        out['assets'].append(entry)
        this_run.append(entry)
        save_report(out_path, out)
    # Once more at the end: a run that skipped everything still leaves its
    # run record.
    save_report(out_path, out)

    # This run's verdict only - one old failure in the appended report must
    # not fail every later run. Skip markers and previews carry no verdict.
    ok = all(r.get('success', True)
             for a in this_run
             for r in (a.get('cesium'), a.get('nira')) if r)
    logger.info('%s %d component(s) this run, skipped %d; report: %s',
                'previewed' if args.dry_run else 'published', len(this_run),
                len(run_record['skipped']), out_path)
    return 0 if ok else 1

if __name__ == '__main__':
    sys.exit(main())
