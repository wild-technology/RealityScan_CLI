#!/usr/bin/env python3
"""Automated CLI test plan for the zone_9 dataset (see testing/TEST_PLAN.md).

Phases:
  0  preflight   - executable/dataset/GPU/flight-log checks, no RealityScan run
  1  smoke       - tiny subset through the full CLI plumbing; verifies the
                   process trigger (results_<instance>.log) actually fires
  2  iterate     - alignment on a stratified subset for the baseline and each
                   preprocessing variant (CLAHE etc.), then a refinement round
                   around the best performer
  3  full        - (only with --full) run the winning variant on the complete
                   zone_9 dataset

Reconstruction-success metric: RealityScan writes one XMP sidecar per
registered camera during -exportXMP, so `registered / total images` is the
primary score, with component count and alignment runtime as tiebreakers.

All RealityScan execution goes through RealityScanCLI (never launched any
other way), per the repo's hard rules. Results append to <work_dir>/results.csv
and a human-readable REPORT.md is rewritten after every phase.

Usage (on the Windows machine with RealityScan 2.2 installed):
  py -3 testing\\run_zone9_tests.py             # phases 0-2
  py -3 testing\\run_zone9_tests.py --full      # phases 0-2 then full-zone run
  py -3 testing\\run_zone9_tests.py --phase 1   # a single phase
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import re
import shutil
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO_ROOT)

from module_base.settings_store import SettingsStore
from modules.realityscan_interface.realityscan_cli import RealityScanCLI, METADATA_DIR
from testing.preprocess_variants import ROUND1_VARIANTS, build_transform, refine_variants

IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png')
CAMERA_RE = re.compile(r'(cam[a-z0-9]+)', re.IGNORECASE)

DEFAULT_DATASET = r'C:\Users\jonat\Desktop\NA173_H2103a\batched_images_by_zone\zone_9'
DEFAULT_WORK_DIR = r'C:\Users\jonat\Desktop\NA173_H2103a\rs_cli_tests'


def make_logger() -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    return logging.getLogger('zone9_tests')


# ----------------------------------------------------------------------
# Dataset helpers
# ----------------------------------------------------------------------

def list_images(directory: str) -> list[str]:
    """Image files in directory, plus one level of camera subfolders
    (zone_9 ships as camlower/cammid/camupper/zeuss dirs). Returns paths
    relative to directory."""
    found: list[str] = []
    for entry in sorted(os.listdir(directory)):
        full = os.path.join(directory, entry)
        if os.path.isdir(full):
            found.extend(os.path.join(entry, name) for name in sorted(os.listdir(full))
                         if name.lower().endswith(IMAGE_EXTENSIONS))
        elif entry.lower().endswith(IMAGE_EXTENSIONS):
            found.append(entry)
    return found


def camera_of(filename: str) -> str:
    parent = os.path.basename(os.path.dirname(filename))
    if parent:
        return parent.lower()
    base = os.path.basename(filename)
    match = CAMERA_RE.search(base)
    if match:
        return match.group(1).lower()
    # zeuss frames carry no camera prefix once flattened, but keep the
    # HERC video-frame token, so they can still be attributed
    return 'zeuss' if 'herc' in base.lower() else 'unknown'


def find_flight_log(dataset_dir: str) -> str:
    candidates = [f for f in os.listdir(dataset_dir)
                  if f.lower().startswith('flight_log') and f.lower().endswith('.txt')]
    if not candidates:
        candidates = [f for f in os.listdir(dataset_dir) if f.lower().endswith('.txt')]
    if len(candidates) != 1:
        raise FileNotFoundError(
            f'Expected exactly one flight log .txt in {dataset_dir}, '
            f'found: {candidates or "none"}')
    return os.path.join(dataset_dir, candidates[0])


def stratified_subset(images: list[str], target: int) -> list[str]:
    """Every-Nth selection per camera so all four cameras stay represented."""
    by_camera: dict[str, list[str]] = {}
    for name in images:
        by_camera.setdefault(camera_of(name), []).append(name)

    per_camera = max(1, target // max(1, len(by_camera)))
    subset = []
    for names in by_camera.values():
        step = max(1, len(names) // per_camera)
        subset.extend(names[::step][:per_camera])
    return sorted(subset)


def materialize_images(source_dir: str, names: list[str], dest_dir: str,
                       transform, flight_log: str, logger) -> None:
    """Copy (or preprocess) the selected images plus the flight log into
    dest_dir. XMP sidecars are never carried over - stale ones would feed
    a previous run's calibration priors into this run and corrupt the
    comparison."""
    import cv2  # deferred so phase 0 can run without opencv installed

    os.makedirs(dest_dir, exist_ok=True)
    start = time.monotonic()
    for index, name in enumerate(names):
        src = os.path.join(source_dir, name)
        # flatten camera subfolders; basenames are unique across cameras
        dst = os.path.join(dest_dir, os.path.basename(name))
        if os.path.exists(dst):
            continue
        if transform is None:
            shutil.copy2(src, dst)
        else:
            image = cv2.imread(src, cv2.IMREAD_COLOR)
            if image is None:
                logger.warning('Unreadable image skipped: %s', src)
                continue
            cv2.imwrite(dst, transform(image), [cv2.IMWRITE_JPEG_QUALITY, 95])
        if index and index % 200 == 0:
            logger.info('  prepared %d/%d images', index, len(names))
    # Write a flight log restricted to the materialized images: rows for
    # images not in the scene make importFlightLog report a failed process
    # (err:18002), which would abort the workflow.
    kept = {os.path.basename(n) for n in names}
    with open(flight_log, encoding='utf-8-sig') as f:
        header, *rows = f.read().splitlines()
    filtered = [header] + [r for r in rows if r.split(';', 1)[0] in kept]
    with open(os.path.join(dest_dir, os.path.basename(flight_log)), 'w',
              encoding='utf-8', newline='') as f:
        f.write('\n'.join(filtered) + '\n')
    logger.info('Prepared %d images in %s (%.1f s)', len(names), dest_dir,
                time.monotonic() - start)


# ----------------------------------------------------------------------
# Alignment + metrics
# ----------------------------------------------------------------------

def run_alignment(cli: RealityScanCLI, image_dir: str, output_dir: str,
                  label: str, logger) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    flight_log = os.path.join(image_dir, os.path.basename(find_flight_log(image_dir)))
    flight_log_params = os.path.join(METADATA_DIR, 'FlightLogParams.xml')

    total_images = len(list_images(image_dir))
    xmp_before = {f for f in os.listdir(image_dir) if f.lower().endswith('.xmp')}
    components_before = {f for f in os.listdir(output_dir)
                         if f.lower().endswith(('.rsalign', '.rcalign'))}

    started = time.monotonic()
    result = cli.run_batch_script(
        'AlignImagesFromFolder.bat',
        [image_dir, output_dir, flight_log, flight_log_params,
         'false', 'false', label, 'false', 'false'],
        os.path.join(output_dir, 'logs'))

    registered = len([f for f in os.listdir(image_dir)
                      if f.lower().endswith('.xmp') and f not in xmp_before])
    components = len([f for f in os.listdir(output_dir)
                      if f.lower().endswith(('.rsalign', '.rcalign'))
                      and f not in components_before])

    xmp_now = {f for f in os.listdir(image_dir) if f.lower().endswith('.xmp')}
    per_camera: dict[str, str] = {}
    camera_totals: dict[str, int] = {}
    camera_registered: dict[str, int] = {}
    for name in list_images(image_dir):
        camera = camera_of(name)
        camera_totals[camera] = camera_totals.get(camera, 0) + 1
        if os.path.splitext(name)[0] + '.xmp' in xmp_now:
            camera_registered[camera] = camera_registered.get(camera, 0) + 1
    for camera in sorted(camera_totals):
        per_camera[camera] = f'{camera_registered.get(camera, 0)}/{camera_totals[camera]}'

    metrics = {
        'label': label,
        'success': result.success,
        'total_images': total_images,
        'registered': registered,
        'registration_rate': round(registered / total_images, 4) if total_images else 0.0,
        'components': components,
        'duration_s': round(time.monotonic() - started, 1),
        'process_count': len(result.completed_processes),
        'errors': (result.errors or '').replace('\n', ' | ')[:300],
        'per_camera': ' '.join(f'{k}={v}' for k, v in per_camera.items()),
        'log': result.log_path or '',
    }
    logger.info('RESULT %s: success=%s registered=%d/%d (%.1f%%) components=%d in %.0fs',
                label, metrics['success'], registered, total_images,
                100 * metrics['registration_rate'], components, metrics['duration_s'])
    return metrics


def append_result(work_dir: str, metrics: dict) -> None:
    path = os.path.join(work_dir, 'results.csv')
    exists = os.path.isfile(path)
    with open(path, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(metrics.keys()))
        if not exists:
            writer.writeheader()
        writer.writerow(metrics)


def write_report(work_dir: str, all_metrics: list[dict], notes: list[str]) -> None:
    lines = ['# zone_9 CLI test report', '']
    lines += [f'- {note}' for note in notes]
    lines += ['', '| run | ok | registered | rate | components | time (s) | per camera |',
              '|---|---|---|---|---|---|---|']
    for m in all_metrics:
        lines.append(f"| {m['label']} | {m['success']} | {m['registered']}/{m['total_images']} "
                     f"| {100 * m['registration_rate']:.1f}% | {m['components']} "
                     f"| {m['duration_s']} | {m['per_camera']} |")
    ranked = [m for m in all_metrics if m['success']]
    if ranked:
        best = max(ranked, key=lambda m: (m['registration_rate'], -m['duration_s']))
        lines += ['', f"**Best so far: `{best['label']}` "
                      f"({100 * best['registration_rate']:.1f}% registered)**"]
    with open(os.path.join(work_dir, 'REPORT.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


# ----------------------------------------------------------------------
# Phases
# ----------------------------------------------------------------------

def phase_preflight(cli: RealityScanCLI, dataset_dir: str, logger) -> None:
    logger.info('=== Phase 0: preflight ===')
    if os.name != 'nt':
        raise SystemExit('This test plan drives RealityScan and must run on the '
                         'Windows machine that has the dataset and RealityScan 2.2.')

    executable = cli.find_executable()
    logger.info('RealityScan executable: %s', executable)

    if not os.path.isdir(dataset_dir):
        raise SystemExit(f'Dataset not found: {dataset_dir}')
    images = list_images(dataset_dir)
    if not images:
        raise SystemExit(f'No images in {dataset_dir}')
    cameras: dict[str, int] = {}
    for name in images:
        cameras[camera_of(name)] = cameras.get(camera_of(name), 0) + 1
    logger.info('Dataset: %d images across %d cameras: %s', len(images), len(cameras),
                ', '.join(f'{k}={v}' for k, v in sorted(cameras.items())))
    if len(cameras) != 4:
        logger.warning('Expected 4 cameras, found %d - check filename prefixes', len(cameras))

    flight_log = find_flight_log(dataset_dir)
    logger.info('Flight log: %s (%d bytes)', flight_log, os.path.getsize(flight_log))

    try:
        gpu = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader'],
                             stdout=subprocess.PIPE, text=True, timeout=30)
        logger.info('GPUs:\n%s', gpu.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        logger.warning('nvidia-smi not available - could not enumerate GPUs')

    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
    except ImportError as error:
        raise SystemExit(f'Missing python dependency ({error.name}). '
                         'Run: py -3 -m pip install opencv-python numpy')
    logger.info('Preflight OK')


def contiguous_subset(images: list[str], target: int) -> list[str]:
    """A consecutive block from the middle of each camera's sequence.
    Unlike the stratified (every-Nth) subset, consecutive frames have real
    overlap, so a tiny smoke set aligns reliably instead of depending on
    borderline component formation."""
    by_camera: dict[str, list[str]] = {}
    for name in images:
        by_camera.setdefault(camera_of(name), []).append(name)
    per_camera = max(1, target // max(1, len(by_camera)))
    subset = []
    for names in by_camera.values():
        start = max(0, (len(names) - per_camera) // 2)
        subset.extend(names[start:start + per_camera])
    return sorted(subset)


def phase_smoke(cli: RealityScanCLI, dataset_dir: str, work_dir: str,
                smoke_size: int, logger) -> dict:
    logger.info('=== Phase 1: smoke test (%d images) ===', smoke_size)
    images = list_images(dataset_dir)
    subset = contiguous_subset(images, smoke_size)
    smoke_dir = os.path.join(work_dir, 'smoke', 'images')
    materialize_images(dataset_dir, subset, smoke_dir, None,
                       find_flight_log(dataset_dir), logger)

    metrics = run_alignment(cli, smoke_dir, os.path.join(work_dir, 'smoke', 'out'),
                            'smoke', logger)
    append_result(work_dir, metrics)

    if metrics['process_count'] == 0:
        raise SystemExit(
            'FATAL: the workflow ran but results_<instance>.log recorded no '
            'finished processes. RealityScan\'s process trigger (appProcessExecCmd '
            '-> ErrorWriter.bat) is not firing, so error detection is dead. Fix '
            'this before trusting any run - see HANDOFF.md checklist item 2 '
            '(quoting in startRealityScan.bat is the usual suspect).')
    if not metrics['success']:
        raise SystemExit(f"Smoke test failed: {metrics['errors'] or 'see log'} "
                         f"({metrics['log']})")
    logger.info('Smoke test passed - CLI plumbing, trigger, and shutdown verified')
    return metrics


def phase_iterate(cli: RealityScanCLI, dataset_dir: str, work_dir: str,
                  subset_size: int, rounds: int, logger) -> list[dict]:
    logger.info('=== Phase 2: preprocessing iteration (subset of %d) ===', subset_size)
    images = list_images(dataset_dir)
    subset = stratified_subset(images, subset_size)
    flight_log = find_flight_log(dataset_dir)

    all_metrics: list[dict] = []
    tested: set[str] = set()
    variants = list(ROUND1_VARIANTS)

    for round_number in range(1, rounds + 1):
        logger.info('--- Round %d: %s ---', round_number,
                    ', '.join(v['name'] for v in variants))
        for params in variants:
            name = params['name']
            tested.add(name)
            variant_dir = os.path.join(work_dir, 'variants', name)
            materialize_images(dataset_dir, subset, os.path.join(variant_dir, 'images'),
                               build_transform(params), flight_log, logger)
            metrics = run_alignment(cli, os.path.join(variant_dir, 'images'),
                                    os.path.join(variant_dir, 'out'), name, logger)
            metrics['variant_params'] = str({k: v for k, v in params.items() if k != 'name'})
            append_result(work_dir, metrics)
            all_metrics.append(metrics)
            write_report(work_dir, all_metrics,
                         [f'subset size: {len(subset)}', f'round: {round_number}'])

        successful = [m for m in all_metrics if m['success']]
        if not successful:
            logger.error('No variant aligned successfully; stopping iteration')
            break
        best = max(successful, key=lambda m: (m['registration_rate'], -m['duration_s']))
        best_params = next((v for v in ROUND1_VARIANTS + variants
                            if v['name'] == best['label']), {'name': best['label']})
        logger.info('Round %d best: %s (%.1f%%)', round_number, best['label'],
                    100 * best['registration_rate'])
        variants = refine_variants(best_params, tested)
        if not variants:
            logger.info('Nothing further to refine (baseline won or neighbors exhausted)')
            break
    return all_metrics


def phase_full(cli: RealityScanCLI, dataset_dir: str, work_dir: str,
               all_metrics: list[dict], logger) -> None:
    logger.info('=== Phase 3: full zone_9 run with winning variant ===')
    successful = [m for m in all_metrics if m['success']]
    if not successful:
        raise SystemExit('No successful subset run - refusing the full-zone run')
    best = max(successful, key=lambda m: (m['registration_rate'], -m['duration_s']))
    params = next((v for v in ROUND1_VARIANTS if v['name'] == best['label']),
                  {'name': best['label']})
    logger.info('Winning variant: %s - this run can take many hours', best['label'])

    images = list_images(dataset_dir)
    full_dir = os.path.join(work_dir, 'full', best['label'])
    materialize_images(dataset_dir, images, os.path.join(full_dir, 'images'),
                       build_transform(params), find_flight_log(dataset_dir), logger)
    metrics = run_alignment(cli, os.path.join(full_dir, 'images'),
                            os.path.join(full_dir, 'out'),
                            f"full_{best['label']}", logger)
    append_result(work_dir, metrics)
    all_metrics.append(metrics)
    write_report(work_dir, all_metrics, ['includes full-zone confirmation run'])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--phase', choices=['0', '1', '2', '3', 'all'], default='all')
    parser.add_argument('--full', action='store_true',
                        help='also run the winning variant on the complete zone')
    parser.add_argument('--rounds', type=int, default=2,
                        help='iteration rounds in phase 2 (default 2)')
    parser.add_argument('--subset-size', type=int, default=400)
    parser.add_argument('--smoke-size', type=int, default=32)
    parser.add_argument('--dataset')
    parser.add_argument('--work-dir')
    args = parser.parse_args()

    logger = make_logger()
    settings = SettingsStore()
    dataset_dir = args.dataset or settings.prompt(
        'zone9_test', 'dataset_dir', 'Zone dataset directory', DEFAULT_DATASET)
    work_dir = args.work_dir or settings.prompt(
        'zone9_test', 'work_dir', 'Test working directory', DEFAULT_WORK_DIR)
    os.makedirs(work_dir, exist_ok=True)

    cli = RealityScanCLI(logger, settings)
    all_metrics: list[dict] = []

    if args.phase in ('0', '1', '2', '3', 'all'):
        phase_preflight(cli, dataset_dir, logger)
    if args.phase in ('1', 'all'):
        phase_smoke(cli, dataset_dir, work_dir, args.smoke_size, logger)
    if args.phase in ('2', 'all'):
        all_metrics = phase_iterate(cli, dataset_dir, work_dir,
                                    args.subset_size, args.rounds, logger)
    if args.phase == '3' or (args.full and args.phase == 'all'):
        phase_full(cli, dataset_dir, work_dir, all_metrics, logger)

    logger.info('Done. Results: %s', os.path.join(work_dir, 'REPORT.md'))


if __name__ == '__main__':
    main()
