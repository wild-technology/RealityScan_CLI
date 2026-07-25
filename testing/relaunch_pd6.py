#!/usr/bin/env python3
"""Relaunch PD-6: zone_1 clean re-align (see HANDOFF "RESTART POINT").

The decisive test of whether the fresh run's hull scale error (0.175)
survives a correct configuration:
  - calibration sidecars restored before the run (the identity harvest
    strips them; FINDINGS 2026-07-25)
  - Division distortion model (validated: best scale, correct for the
    fisheye, no harm to the rectilinear camera)
  - LOOSE 10/10/1 position priors (tight priors fragment - bow 2x2)

The fixture is already staged at D:/na156_h2023_fresh/pd_runs/
pd6_zone_1_clean. Safe to re-run: it only writes into that folder plus
the zone's sidecars. Expect 80-110 min.

Baseline to beat: 4,405/4,540 in 3 components, hull scale 0.175/0.221,
bow 1.009.
"""
import logging
import os
import shutil
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO)

from modules import camera_registry
from modules.realityscan_interface.realityscan_cli import RealityScanCLI
from testing import scale_oracle

CELL = r'D:/na156_h2023_fresh/pd_runs/pd6_zone_1_clean'
ZONE = r'D:/na156_h2023_fresh/batched_images_by_zone/zone_1'


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    logger = logging.getLogger('pd6')
    components = os.path.join(CELL, 'components')
    os.makedirs(components, exist_ok=True)

    created, unknown = camera_registry.ensure_calibration_sidecars(ZONE)
    logger.info('calibration sidecars restored: %d (unknown cameras: %d)',
                created, unknown)

    os.environ['RS_ALIGN_PARAMS'] = os.path.join(
        CELL, 'AlignmentParams_division.xml').replace('/', os.sep)
    cli = RealityScanCLI(logger)
    start = time.time()
    result = cli.run_batch_script('AlignZone.bat', [
        ZONE, components,
        os.path.join(CELL, 'flight_log_4Q_UTM.txt'),
        os.path.join(CELL, 'FlightLogParams_4Q.xml'), 'pd6_zone_1', '50'],
        os.path.join(CELL, 'logs'))
    os.environ.pop('RS_ALIGN_PARAMS', None)

    try:
        shutil.copyfile(
            os.path.join(os.environ['LOCALAPPDATA'], 'Temp', 'RealityScan.log'),
            os.path.join(CELL, 'rslog.txt'))
    except OSError as exc:
        logger.warning('could not snapshot RealityScan.log: %s', exc)

    camera_registry.sanitize_and_census(ZONE)

    rows = scale_oracle.report(components, os.path.join(CELL, 'flight_log_4Q_UTM.txt'))
    print(f'PD-6 zone_1 CLEAN: success={result.success} '
          f'{(time.time() - start) / 60:.1f} min')
    print('  baseline: 4405/4540, 3 comps, hull scale 0.175/0.221, bow 1.009')
    for row in rows:
        print('  c{component}: {cameras:5d} cams  SCALE {median:.3f}  '
              'IQR {iqr_low:.3f}-{iqr_high:.3f}'.format(**row))
    print('  total registered:', sum(r['cameras'] for r in rows))
    return 0 if result.success else 1


if __name__ == '__main__':
    sys.exit(main())
