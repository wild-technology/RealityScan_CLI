#!/usr/bin/env python3
"""D7 + Q9 merge-mechanism probe (see testing/MERGE_TEST_PLAN.md,
"D7 probe wave").

Builds a zero-overlap duplicate-path pair from the smoke minis, aligns
both via AlignZone.bat (the first align doubles as the hook-chain
liveness self-test), then runs four merge cells that isolate WHAT fused
the NA156 duplicate-path components:

  D7b_zero_nolog       merge, zero-overlap pair, no constraints  (known-bad)
  D7a_zero_log         merge, zero-overlap pair, union log + -update (decisive)
  Q9a_content_align    align+rematch, content-overlap pair, no constraints
  D7c_repl_overlap_log merge, content-overlap pair, union log (known-good)

Judged by pose-XMP census (sanitized after every read) + RealityScan.log
snapshots. Writes probe_results.json incrementally; ASCII-only output.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO)

from modules import camera_registry
from modules.flight_logs import write_flight_log_params
from modules.realityscan_interface.realityscan_cli import (
    RealityScanCLI, METADATA_DIR, ERRORS_DIR)

SMOKE = 'D:/na156_h2023/smoke_test'
ZONES = f'{SMOKE}/zones'
ZONES_D7 = f'{SMOKE}/zones_d7'
COMPS = f'{SMOKE}/aligned_components'
COMPS_D7 = f'{SMOKE}/aligned_components_d7'
OUT = f'{SMOKE}/probe_d7'
MIN_SIZE = 10

RESULTS_PATH = os.path.join(OUT, 'probe_results.json')
RS_LOG = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Temp', 'RealityScan.log')


def census(root: str, logger) -> int:
    registered, _restored, removed = camera_registry.sanitize_and_census(root)
    if removed:
        logger.warning('%d unknown-camera pose sidecars removed under %s',
                       removed, root)
    return registered


def filtered_log(src_log: str, basenames: set[str], dst_log: str) -> int:
    with open(src_log, encoding='utf-8') as f:
        lines = f.read().splitlines()
    rows = [l for l in lines[1:]
            if l.strip() and l.split(';')[0].strip('"').lower() in basenames]
    with open(dst_log, 'w', encoding='utf-8', newline='\r\n') as f:
        f.write(lines[0] + '\n' + '\n'.join(rows) + '\n')
    return len(rows)


def union_log(src_logs: list[str], dst_log: str) -> int:
    header, rows = None, {}
    for path in src_logs:
        with open(path, encoding='utf-8') as f:
            lines = f.read().splitlines()
        header = header or lines[0]
        for line in lines[1:]:
            if line.strip():
                rows.setdefault(line.split(';')[0].strip('"').lower(), line)
    with open(dst_log, 'w', encoding='utf-8', newline='\r\n') as f:
        f.write(header + '\n' + '\n'.join(rows.values()) + '\n')
    return len(rows)


def build_zero_overlap_zones(logger) -> tuple[set[str], set[str]]:
    """zone_c = mini_a-only basenames, zone_d = mini_b-only. Copies image
    + calibration sidecar; writes each zone's filtered flight log."""
    a_dir, b_dir = f'{ZONES}/mini_a', f'{ZONES}/mini_b'
    jpgs = lambda d: {f.lower() for f in os.listdir(d) if f.lower().endswith('.jpg')}
    a, b = jpgs(a_dir), jpgs(b_dir)
    only = {'zone_c': (a - b, a_dir), 'zone_d': (b - a, b_dir)}
    sets = {}
    for zone, (names, src_dir) in only.items():
        dst_dir = f'{ZONES_D7}/{zone}'
        os.makedirs(dst_dir, exist_ok=True)
        copied = 0
        for f in os.listdir(src_dir):
            fl = f.lower()
            stem_jpg = fl if fl.endswith('.jpg') else fl[:-4] + '.jpg'
            if (fl.endswith('.jpg') or fl.endswith('.xmp')) and stem_jpg in names:
                if not os.path.exists(os.path.join(dst_dir, f)):
                    shutil.copy2(os.path.join(src_dir, f), os.path.join(dst_dir, f))
                copied += 1
        n = filtered_log(f'{src_dir}/flight_log_4Q_UTM.txt', names,
                         f'{dst_dir}/flight_log_4Q_UTM.txt')
        logger.info('%s: %d files staged, %d flight-log rows', zone, copied, n)
        sets[zone] = names
    assert not (sets['zone_c'] & sets['zone_d']), 'zones must not share basenames'
    return sets['zone_c'], sets['zone_d']


def snapshot(dest: str, logger) -> str:
    try:
        shutil.copyfile(RS_LOG, dest)
        with open(dest, encoding='utf-8', errors='replace') as f:
            fin = [l.strip() for l in f if 'inalizing' in l]
        return '; '.join(fin[-4:])
    except OSError as exc:
        logger.warning('RS log snapshot failed: %s', exc)
        return ''


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(os.path.join(OUT, 'probe_d7.log'),
                                      encoding='utf-8')])
    logger = logging.getLogger('probe_d7')
    results = {'started': time.strftime('%Y-%m-%d %H:%M:%S'), 'cells': {}}

    def flush():
        with open(RESULTS_PATH, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2)

    # Stage 0 - fixtures + hygiene (no stray pose sidecars anywhere).
    zc, zd = build_zero_overlap_zones(logger)
    for root in (ZONES, ZONES_D7):
        pre = census(root, logger)
        if pre:
            logger.warning('%d stray pose sidecars sanitized under %s', pre, root)
    params = write_flight_log_params(
        os.path.join(METADATA_DIR, 'FlightLogParams.xml'),
        os.path.join(OUT, 'FlightLogParams_4Q.xml'), 4, 'Q')

    cli = RealityScanCLI(logger)
    logs_dir = os.path.join(OUT, 'logs')

    # Stage 1 - align the two zero-overlap zones. First run = liveness test.
    aligned = {}
    for zone in ('zone_c', 'zone_d'):
        comp_dir = f'{COMPS_D7}/{zone}'
        os.makedirs(comp_dir, exist_ok=True)
        t0 = time.time()
        res = cli.run_batch_script('AlignZone.bat', [
            f'{ZONES_D7}/{zone}', comp_dir,
            f'{ZONES_D7}/{zone}/flight_log_4Q_UTM.txt', params,
            zone, str(MIN_SIZE)], logs_dir)
        # Census: identity_r0 = full registration of the last align.
        r0 = os.path.join(comp_dir, 'identity_r0')
        reg = len([f for f in os.listdir(r0)]) if os.path.isdir(r0) else 0
        comps = [f for f in os.listdir(comp_dir) if f.endswith('.rsalign')]
        cell = {'workflow_success': res.success, 'errors': res.errors,
                'registered': reg, 'components': sorted(comps),
                'duration_s': round(time.time() - t0, 1),
                'finalizing': snapshot(os.path.join(OUT, f'rslog_{zone}.txt'), logger)}
        results['cells'][f'P0_align_{zone[-1]}'] = cell
        census(ZONES_D7, logger)  # sidecar hygiene after any export
        if zone == 'zone_c':
            # Hook-chain liveness self-test (CRLF normalization touched the
            # hook scripts on 07-24): the results log must be non-empty.
            rlog = os.path.join(ERRORS_DIR, f'results_{cli.instance_name}.log')
            live = os.path.isfile(rlog) and os.path.getsize(rlog) > 0
            results['hook_liveness'] = bool(live)
            flush()
            if not live:
                logger.error('HOOK CHAIN DEAD: %s empty after a full workflow '
                             '- aborting probe (monitor channel broken)', rlog)
                return 2
        flush()
        if not res.success or not comps:
            logger.error('%s align failed or produced no component - abort', zone)
            return 1
        aligned[zone] = os.path.join(comp_dir, sorted(comps)[0])
        logger.info('%s: %d registered, components: %s', zone, reg, comps)

    # Union flight logs for the log-bearing cells.
    zero_union = os.path.join(OUT, 'flight_log_zero_4Q_UTM.txt')
    union_log([f'{ZONES_D7}/zone_c/flight_log_4Q_UTM.txt',
               f'{ZONES_D7}/zone_d/flight_log_4Q_UTM.txt'], zero_union)
    over_union = os.path.join(OUT, 'flight_log_over_4Q_UTM.txt')
    union_log([f'{ZONES}/mini_a/flight_log_4Q_UTM.txt',
               f'{ZONES}/mini_b/flight_log_4Q_UTM.txt'], over_union)

    mini_pair = [f'{COMPS}/mini_a/mini_a_c0.rsalign',
                 f'{COMPS}/mini_b/Component 2.rsalign']
    zero_pair = [aligned['zone_c'], aligned['zone_d']]

    cells = [
        ('D7b_zero_nolog', zero_pair, 'merge',
         ['sfmMergeGeoreferencedComponents:true', 'sfmEnableCameraPrior:true'],
         None, ZONES_D7),
        ('D7a_zero_log', zero_pair, 'merge',
         ['sfmMergeGeoreferencedComponents:true', 'sfmEnableCameraPrior:true'],
         zero_union, ZONES_D7),
        ('Q9a_content_align_nolog', mini_pair, 'align',
         ['sfmForceComponentRematch:true'], None, ZONES),
        ('D7c_repl_overlap_log', mini_pair, 'merge',
         ['sfmMergeGeoreferencedComponents:true', 'sfmEnableCameraPrior:true'],
         over_union, ZONES),
    ]

    for label, pair, mode, settings, log, images_root in cells:
        for comp in pair:
            if not os.path.isfile(comp):
                logger.error('%s: missing component %s - skipping cell', label, comp)
                results['cells'][label] = {'skipped': f'missing {comp}'}
                flush()
                break
        else:
            cell_dir = os.path.join(OUT, label)
            os.makedirs(cell_dir, exist_ok=True)
            complist = os.path.join(cell_dir, 'pair.complist')
            with open(complist, 'w', encoding='ascii', newline='\r\n') as f:
                f.write('\n'.join(pair) + '\n')
            if log:
                os.environ['RS_MERGE_FLIGHT_LOG'] = log
                os.environ['RS_MERGE_FLIGHT_LOG_PARAMS'] = params
            else:
                os.environ.pop('RS_MERGE_FLIGHT_LOG', None)
                os.environ.pop('RS_MERGE_FLIGHT_LOG_PARAMS', None)
            logger.info('--- cell %s: mode=%s log=%s ---', label, mode, bool(log))
            t0 = time.time()
            res = cli.run_batch_script(
                'MergeZoneComponents.bat',
                [complist, cell_dir, label, mode, str(MIN_SIZE)] + settings,
                logs_dir)
            reg = census(images_root, logger)
            results['cells'][label] = {
                'workflow_success': res.success, 'errors': res.errors,
                'census_maximal': reg,
                'duration_s': round(time.time() - t0, 1),
                'finalizing': snapshot(os.path.join(OUT, f'rslog_{label}.txt'),
                                       logger),
            }
            flush()
            logger.info('cell %s: success=%s census=%d', label, res.success, reg)

    results['finished'] = time.strftime('%Y-%m-%d %H:%M:%S')
    flush()
    logger.info('Probe complete: %s', RESULTS_PATH)
    return 0


if __name__ == '__main__':
    sys.exit(main())
