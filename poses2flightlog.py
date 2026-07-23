#!/usr/bin/env python3
"""Rewrite camera locations back to UTM from RealityScan's computed poses.

The USBL/DVL flight logs are position *estimates*; after alignment the
bundle-adjusted poses are better relative geometry. RealityScan's XMP
sidecars (exportXMPForSelectedComponent in the workflow scripts) store
those poses, but in a grid-anchored LOCAL Euclidean frame, not UTM
(verified on zone_9: xcr:Position is local, the anchor is the grid
origin, and the lat/long XMP attributes are garbage).

This tool estimates the rigid local->UTM transform by least squares
(Umeyama, scale locked to 1) between the XMP camera positions and the
matching flight-log priors, then writes a refined flight log in the same
13-column format:

- registered images get the transformed (refined) X/Y/Alt; yaw/pitch/roll
  and their accuracies are carried over from the original log (the XMP
  rotation convention has not been validated against the flight-log
  convention, so orientations are deliberately NOT rewritten);
- unregistered images keep their original rows (drop with
  --registered-only);
- per-image residuals (refined minus prior, in meters) go to a QC CSV -
  the residual magnitude is an estimate of the USBL/DVL navigation error.

Scale stays locked at 1: the alignment already pins scale via the camera
priors, and fitting scale against noise-dominated nav data collapses it
toward zero (observed 0.5 on zone_9). --allow-scale exists for
diagnostics only.

Usage:
  py -3 poses2flightlog.py [--images-dir DIR] [--flight-log FILE]
                           [--output FILE] [--position-accuracy M]
                           [--registered-only] [--allow-scale]

All prompts default to the previous run's answers (rs_settings.json).
"""

from __future__ import annotations

import argparse
import csv
import glob
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from module_base.settings_store import SettingsStore

POSITION_RE = re.compile(r'<xcr:Position>([^<]+)</xcr:Position>')
MIN_CAMERAS = 3


def read_xmp_positions(images_dir: str) -> dict[str, np.ndarray]:
    """Image stem -> local camera position from the XMP sidecars."""
    positions = {}
    for path in glob.glob(os.path.join(images_dir, '*.xmp')):
        with open(path, encoding='utf-8') as f:
            match = POSITION_RE.search(f.read())
        if match:
            stem = os.path.splitext(os.path.basename(path))[0]
            positions[stem] = np.array([float(v) for v in match.group(1).split()])
    return positions


def row_xyz(row: list[str]) -> list[float] | None:
    """X/Y/Alt of a flight-log row as floats, or None when the row has no
    usable position (the georeference module legitimately writes empty
    fields for images matched in time but missing GPS)."""
    try:
        return [float(row[1]), float(row[2]), float(row[3])]
    except (ValueError, IndexError):
        return None


def read_flight_log(path: str) -> tuple[str, list[list[str]]]:
    with open(path, encoding='utf-8-sig') as f:
        header = f.readline().rstrip('\n')
        rows = [line.rstrip('\n').split(';') for line in f if line.strip()]
    return header, rows


def umeyama_rigid(src: np.ndarray, dst: np.ndarray, with_scale: bool = False):
    """Least-squares src->dst transform: returns (scale, R, t)."""
    mu_s, mu_d = src.mean(0), dst.mean(0)
    src_c, dst_c = src - mu_s, dst - mu_d
    cov = dst_c.T @ src_c / len(src)
    U, D, Vt = np.linalg.svd(cov)
    S = np.eye(3)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        S[2, 2] = -1
    R = U @ S @ Vt
    scale = (np.trace(np.diag(D) @ S) / src_c.var(0).sum()) if with_scale else 1.0
    t = mu_d - scale * R @ mu_s
    return scale, R, t


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--images-dir', help='Aligned image directory containing the .xmp sidecars')
    parser.add_argument('--flight-log', help='Original flight log (default: the single *_UTM.txt in the images dir)')
    parser.add_argument('--output', help='Refined flight log path (default: <flight log>_refined.txt)')
    parser.add_argument('--position-accuracy', type=float, default=1.0,
                        help='X/Y/Alt accuracy (m) written for refined rows (default 1.0)')
    parser.add_argument('--registered-only', action='store_true',
                        help='Drop images without a computed pose instead of keeping their original rows')
    parser.add_argument('--allow-scale', action='store_true',
                        help='Also fit scale (diagnostics only - nav noise biases it low)')
    args = parser.parse_args()

    settings = SettingsStore()
    images_dir = args.images_dir or settings.prompt(
        'poses2flightlog', 'images_dir', 'Aligned image directory (with .xmp sidecars)', None)
    if not images_dir or not os.path.isdir(images_dir):
        sys.exit(f'Not a directory: {images_dir}')

    flight_log = args.flight_log
    if not flight_log:
        candidates = glob.glob(os.path.join(images_dir, '*_UTM.txt')) or \
                     glob.glob(os.path.join(images_dir, 'flight_log*.txt'))
        if len(candidates) == 1:
            flight_log = candidates[0]
            print(f'Flight log: {flight_log}')
        else:
            flight_log = settings.prompt('poses2flightlog', 'flight_log',
                                         'Original flight log path', None)
    if not flight_log or not os.path.isfile(flight_log):
        sys.exit(f'Flight log not found: {flight_log}')

    output = args.output or f'{os.path.splitext(flight_log)[0]}_refined.txt'

    positions = read_xmp_positions(images_dir)
    header, rows = read_flight_log(flight_log)
    print(f'{len(positions)} XMP poses, {len(rows)} flight log rows')

    by_stem = {os.path.splitext(r[0])[0]: r for r in rows}
    common = sorted(set(positions) & set(by_stem))

    # Fit only on rows that actually carry a position prior; registered
    # images with empty X/Y/Alt still get refined coordinates from the
    # transform, they just cannot help estimate it.
    fit_stems = [s for s in common if row_xyz(by_stem[s]) is not None]
    skipped_no_prior = len(common) - len(fit_stems)
    if skipped_no_prior:
        print(f'{skipped_no_prior} matched rows have no position prior - '
              'excluded from the transform fit')
    if len(fit_stems) < MIN_CAMERAS:
        sys.exit(f'Only {len(fit_stems)} registered images have usable flight-log '
                 f'positions - need at least {MIN_CAMERAS} to estimate the transform')

    local = np.array([positions[s] for s in fit_stems])
    utm = np.array([row_xyz(by_stem[s]) for s in fit_stems])

    scale, R, t = umeyama_rigid(local, utm, with_scale=args.allow_scale)
    # Refined output positions for EVERY matched stem; residuals only where
    # a prior exists to compare against
    all_local = np.array([positions[s] for s in common])
    refined_all = scale * (R @ all_local.T).T + t
    refined_fit = scale * (R @ local.T).T + t
    residuals = refined_fit - utm
    norms = np.linalg.norm(residuals, axis=1)
    print(f'Rigid fit over {len(fit_stems)} cameras'
          + (f' (scale={scale:.5f})' if args.allow_scale else '')
          + f': residual vs prior [m] mean {norms.mean():.2f}, '
            f'median {np.median(norms):.2f}, p95 {np.percentile(norms, 95):.2f}, '
            f'max {norms.max():.2f}')
    print('(residual magnitude ~ USBL/DVL navigation error estimate)')

    refined_by_stem = dict(zip(common, refined_all))
    acc = f'{args.position_accuracy:.6f}'
    written = kept = 0
    with open(output, 'w', encoding='utf-8', newline='') as f:
        f.write(header + '\n')
        for row in rows:
            stem = os.path.splitext(row[0])[0]
            if stem in refined_by_stem:
                x, y, z = refined_by_stem[stem]
                new_row = list(row)
                new_row[1:7] = [f'{x:.6f}', f'{y:.6f}', f'{z:.6f}', acc, acc, acc]
                f.write(';'.join(new_row) + '\n')
                written += 1
            elif not args.registered_only:
                f.write(';'.join(row) + '\n')
                kept += 1
    print(f'Wrote {output}: {written} refined rows'
          + ('' if args.registered_only else f', {kept} original rows kept'))

    qc_path = f'{os.path.splitext(output)[0]}_residuals.csv'
    with open(qc_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['filename', 'd_east_m', 'd_north_m', 'd_up_m', 'distance_m'])
        for stem, delta, norm in sorted(zip(fit_stems, residuals, norms),
                                        key=lambda item: -item[2]):
            writer.writerow([by_stem[stem][0]] + [f'{v:.3f}' for v in delta] + [f'{norm:.3f}'])
    print(f'Per-image residual QC: {qc_path}')

    unmatched = len(positions) - len(common)
    if unmatched:
        print(f'NOTE: {unmatched} registered images had no flight-log row and were not written')


if __name__ == '__main__':
    main()
