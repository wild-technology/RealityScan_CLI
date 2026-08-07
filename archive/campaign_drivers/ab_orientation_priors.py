#!/usr/bin/env python3
"""Overnight A/B: do ORIENTATION PRIORS cause the H2024 scale collapse?

THE QUESTION
------------
The 2026-07-26 H2024 production aligns ran with orientation priors ON at 15 deg
and produced one catastrophically broken component - zone_3 c0, 1,192 cameras at
scale 0.236 - plus two more outside a +/-10% band (zone_4 c2 1.196, c4 1.100)
and an 8-way fragmentation of zone_1. Registration looked healthy throughout
(82-93% per zone, Success=True everywhere), so only the metric-scale oracle
caught it.

Attribution is unproven because three things differ from the last known-sound
run (PD-6, H2023): the dataset, orientation priors, and the fact that the
import's Euler-angle order and Camera-mount settings are NOT pinned - so the
YPR we supply may be composed in an order our numbers do not assume.

THE EXPERIMENT
--------------
Re-align all five zones changing EXACTLY ONE VARIABLE: the flight log carries
positions only (7-column format {0E9850E2-...}) instead of positions plus YPR
(13-column {B438A617-...}). Everything else - images, AlignmentParams,
calibration sidecars, position accuracies, min component size - is identical.

NON-DESTRUCTIVE: writes to <workspace>/ab_position_only/<zone>/. The
orientation-ON results in aligned_components/ are left untouched, so the owner
wakes to a genuine A/B rather than a replacement.

DECISION RULE (stated before the run, per the working agreement)
---------------------------------------------------------------
For each zone, compare the maximal component's scale against the orientation-ON
figure recorded in ORIENTATION_ON below:
  * zone_3 returns to 0.90-1.10  -> orientation priors under an unpinned Euler
    order are the cause. Pull them until the GUI diff settles the convention.
  * zone_3 stays ~0.24          -> priors are exonerated; the cause is the
    dataset or the solve, and the next suspect is the DVL-dominated nav regime
    (review finding M7).
  * mixed across zones          -> report per zone, conclude nothing global.

BUDGET
------
Five zones, 1,279-2,983 images each. H2023 comparables ran 20-90 min per zone,
so expect 2.5-5 h total. Peak RAM well under the box; cache pinned to E: (7.4 TB
free) because the cache disk, not the project disk, is what killed three hull
model attempts. ABORT CRITERIA: a zone stalling >45 min with no progress, exit
code 3, or free space on E: dropping below 200 GB.

RESUMABLE: a zone whose results are already in the JSON is skipped, so the run
can be restarted after an interruption without redoing work.

Run DETACHED (it must outlive the launching shell):
    powershell -NoProfile -Command "Start-Process py -ArgumentList '-3.13',
      'testing/ab_orientation_priors.py' -WindowStyle Hidden
      -RedirectStandardOutput F:/_copylogs/ab_orientation.log
      -RedirectStandardError  F:/_copylogs/ab_orientation.err"
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
from modules import scale_oracle
from modules.flight_logs import write_flight_log_params
from modules.realityscan_interface.realityscan_cli import (
    METADATA_DIR, RealityScanCLI)

WORKSPACE = 'F:/na156_h2024'
ZONES_ROOT = f'{WORKSPACE}/batched_images_by_zone'
OUT_ROOT = f'{WORKSPACE}/ab_position_only'
RESULTS = f'{OUT_ROOT}/ab_results.json'
CACHE_DIR = r'E:\rscache'
MIN_FREE_CACHE_GB = 200.0

# 7-column position-only parser (verified in Program Files flightlogs.xml):
# Image, X, Y, Altitude, XAccuracy, YAccuracy, AltitudeAccuracy.
POSITION_ONLY_GUID = '{0E9850E2-73E1-4538-B2CF-B18BEF6CECEB}'

ZONES = ['zone_1', 'zone_2', 'zone_3', 'zone_4', 'zone_5']

# Maximal-component scale measured 2026-07-26 with orientation priors ON.
ORIENTATION_ON = {
    'zone_1': 1.076, 'zone_2': 1.086, 'zone_3': 0.236,
    'zone_4': 0.983, 'zone_5': 1.023,
}


def make_position_only_log(src: str, dst: str) -> int:
    """Strip Yaw/Pitch/Roll and their accuracies, keeping columns 0-6."""
    rows = 0
    with open(src, encoding='utf-8', errors='replace') as fh_in, \
         open(dst, 'w', encoding='utf-8', newline='\r\n') as fh_out:
        for i, line in enumerate(fh_in):
            parts = line.rstrip('\r\n').split(';')
            if len(parts) < 7:
                continue
            fh_out.write(';'.join(parts[:7]) + '\n')
            if i:
                rows += 1
    return rows


def make_params(zone_tag: str, dst: str) -> str:
    """FlightLogParams pinned to the position-only format for this UTM zone."""
    template = os.path.join(METADATA_DIR, 'FlightLogParams.xml')
    zone_num = int(''.join(c for c in zone_tag if c.isdigit()))
    band = ''.join(c for c in zone_tag if c.isalpha()).upper()
    write_flight_log_params(template, dst, zone_num, band)
    text = open(dst, encoding='utf-8').read()
    # swap the 13-column YPR format for the 7-column position-only one
    import re
    text = re.sub(r'(<entry key="gpsLogFileFormat" value=")\{[^}]+\}',
                  r'\g<1>' + POSITION_ONLY_GUID, text)
    open(dst, 'w', encoding='utf-8').write(text)
    return dst


def load_results() -> dict:
    if os.path.isfile(RESULTS):
        try:
            with open(RESULTS, encoding='utf-8') as fh:
                return json.load(fh)
        except (OSError, ValueError):
            pass
    return {'zones': {}}


def save_results(data: dict) -> None:
    tmp = RESULTS + '.part'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, RESULTS)


def cache_free_gb() -> float:
    try:
        return shutil.disk_usage(CACHE_DIR).free / (1024 ** 3)
    except OSError:
        return float('inf')


def run_zone(cli: RealityScanCLI, zone: str, logger) -> dict:
    zone_dir = f'{ZONES_ROOT}/{zone}'
    out_dir = f'{OUT_ROOT}/{zone}'
    comps = f'{out_dir}/components'
    logs = f'{out_dir}/logs'
    os.makedirs(comps, exist_ok=True)

    src_log = f'{zone_dir}/flight_log_4Q_UTM.txt'
    if not os.path.isfile(src_log):
        return {'status': 'error', 'reason': f'missing flight log {src_log}'}

    pos_log = f'{out_dir}/flight_log_4Q_UTM.txt'
    rows = make_position_only_log(src_log, pos_log)
    params = make_params('4Q', f'{out_dir}/FlightLogParams_4Q.xml')
    logger.info('%s: position-only log %d rows -> %s', zone, rows, pos_log)

    # The identity harvest MOVES calibration sidecars out of the image tree; a
    # re-align without them runs with a partially ungrouped camera set, which is
    # what confounded PD-4/PD-4a. Restore before every align.
    created, unknown = camera_registry.ensure_calibration_sidecars(zone_dir)
    logger.info('%s: calibration sidecars restored %d (unknown %d)',
                zone, created, unknown)

    start = time.time()
    result = cli.run_batch_script(
        'AlignZone.bat',
        [zone_dir, comps, pos_log, params, f'ab_{zone}', '50'],
        logs)
    minutes = (time.time() - start) / 60.0

    camera_registry.sanitize_and_census(zone_dir)

    rowsout = []
    try:
        rowsout = scale_oracle.report(comps, src_log)
    except Exception as exc:  # measurement must never lose the align
        logger.warning('%s: scale measurement failed: %s', zone, exc)

    maximal = rowsout[0] if rowsout else None
    entry = {
        'status': 'ok' if result.success else 'align_failed',
        'minutes': round(minutes, 1),
        'errors': result.errors,
        'components': [
            {'component': r['component'], 'cameras': r['cameras'],
             'scale': round(r['median'], 3),
             'iqr': [round(r['iqr_low'], 3), round(r['iqr_high'], 3)],
             'verdict': scale_oracle.verdict(r)[0]}
            for r in rowsout],
        'maximal_scale': None if maximal is None else round(maximal['median'], 3),
        'orientation_on_scale': ORIENTATION_ON.get(zone),
    }
    if entry['maximal_scale'] is not None:
        before = entry['orientation_on_scale']
        entry['verdict_vs_orientation_on'] = (
            'position-only IN BAND, orientation-on was OUT'
            if 0.90 <= entry['maximal_scale'] <= 1.10 and before is not None
            and not (0.90 <= before <= 1.10)
            else 'both in band' if 0.90 <= entry['maximal_scale'] <= 1.10
            else 'position-only STILL OUT of band')
    return entry


def main() -> int:
    os.makedirs(OUT_ROOT, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        handlers=[logging.FileHandler(f'{OUT_ROOT}/ab_driver.log', encoding='utf-8'),
                  logging.StreamHandler(sys.stdout)])
    logger = logging.getLogger('ab')

    os.environ['RS_CACHE_DIR'] = CACHE_DIR
    os.environ['RS_HEADLESS'] = '1'

    logger.info('=' * 70)
    logger.info('A/B: orientation priors ON (recorded) vs POSITION-ONLY (this run)')
    logger.info('cache=%s free=%.0f GB', CACHE_DIR, cache_free_gb())
    logger.info('=' * 70)

    data = load_results()
    cli = RealityScanCLI(logger)

    for zone in ZONES:
        if zone in data['zones'] and data['zones'][zone].get('status') == 'ok':
            logger.info('%s already done (scale %s) - skipping', zone,
                        data['zones'][zone].get('maximal_scale'))
            continue
        free = cache_free_gb()
        if free < MIN_FREE_CACHE_GB:
            logger.error('ABORT: cache disk down to %.0f GB (floor %.0f) - the '
                         'cache disk is what killed three hull attempts',
                         free, MIN_FREE_CACHE_GB)
            data['aborted'] = f'cache disk {free:.0f} GB'
            save_results(data)
            return 1
        logger.info('--- %s: aligning POSITION-ONLY (cache free %.0f GB) ---',
                    zone, free)
        try:
            data['zones'][zone] = run_zone(cli, zone, logger)
        except Exception as exc:
            logger.exception('%s raised', zone)
            data['zones'][zone] = {'status': 'exception', 'reason': str(exc)}
        save_results(data)
        z = data['zones'][zone]
        logger.info('%s: %s in %s min, maximal scale %s (orientation-on was %s) %s',
                    zone, z.get('status'), z.get('minutes'), z.get('maximal_scale'),
                    z.get('orientation_on_scale'),
                    z.get('verdict_vs_orientation_on', ''))

    logger.info('=' * 70)
    logger.info('A/B COMPLETE - summary')
    for zone in ZONES:
        z = data['zones'].get(zone, {})
        logger.info('  %-8s position-only %-7s vs orientation-on %-7s  %s',
                    zone, z.get('maximal_scale'), z.get('orientation_on_scale'),
                    z.get('verdict_vs_orientation_on', z.get('status', 'not run')))
    logger.info('Results JSON: %s', RESULTS)
    logger.info('=' * 70)
    save_results(data)
    return 0


if __name__ == '__main__':
    sys.exit(main())
