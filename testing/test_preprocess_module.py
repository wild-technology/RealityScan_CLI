#!/usr/bin/env python3
"""Functional test for the PreprocessImages pipeline module.

Runs the module over a small slice of a real dataset and checks the
properties the pipeline depends on:

- folder structure is mirrored and filenames are preserved exactly
  (per-zone flight-log matching is by filename - see CLAUDE.md);
- output is byte-identical to the canonical transform used by the A/B
  harness, so testing/ and the pipeline can never silently diverge;
- a rerun skips already-processed images (interrupted runs resume);
- CLAHE actually altered the pixels.

Usage (defaults to the zone_9 dataset):
  py -3 testing\\test_preprocess_module.py
  py -3 testing\\test_preprocess_module.py --dataset D:\\some\\zone
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO_ROOT)

import cv2
import numpy as np

from module_base.parameter import Parameter
from module_base.settings_store import SettingsStore
from modules.preprocess_images.preprocess_images import PreprocessImages, build_transform

# Seed only - the dataset answer stored by run_zone9_tests wins when set
# (repo hard rule 5: never hardcode data paths).
DEFAULT_DATASET = r'M:\NA173_H2103a\batched_images_by_zone\zone_9'
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png')
PER_CAMERA = 20


def sample_cameras(dataset: str, limit: int = 2) -> list[str]:
    """Up to `limit` camera subfolders that contain images (falls back to
    the dataset root when the images are not in subfolders)."""
    subdirs = [d for d in sorted(os.listdir(dataset))
               if os.path.isdir(os.path.join(dataset, d))
               and any(f.lower().endswith(IMAGE_EXTENSIONS)
                       for f in os.listdir(os.path.join(dataset, d)))]
    return subdirs[:limit] or ['']


def stage_input(dataset: str, cameras: list[str], input_dir: str) -> int:
    staged = 0
    for cam in cameras:
        src_dir = os.path.join(dataset, cam) if cam else dataset
        dst_dir = os.path.join(input_dir, cam) if cam else input_dir
        os.makedirs(dst_dir, exist_ok=True)
        names = [f for f in sorted(os.listdir(src_dir))
                 if f.lower().endswith(IMAGE_EXTENSIONS)][:PER_CAMERA]
        for name in names:
            shutil.copy2(os.path.join(src_dir, name), dst_dir)
        staged += len(names)
    return staged


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dataset',
                        default=SettingsStore().get('zone9_test', 'dataset_dir', DEFAULT_DATASET),
                        help='Dataset to sample images from')
    parser.add_argument('--work-dir', help='Where to stage the test (default: a temp dir)')
    args = parser.parse_args()

    if not os.path.isdir(args.dataset):
        sys.exit(f'Dataset not found: {args.dataset} (pass --dataset)')

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger('preprocess_module_test')

    temp_dir = None
    if args.work_dir:
        work_dir = args.work_dir
        shutil.rmtree(work_dir, ignore_errors=True)
        os.makedirs(work_dir)
    else:
        temp_dir = tempfile.mkdtemp(prefix='rs_preprocess_test_')
        work_dir = temp_dir

    try:
        cameras = sample_cameras(args.dataset)
        input_dir = os.path.join(work_dir, 'input')
        expected_count = stage_input(args.dataset, cameras, input_dir)
        assert expected_count, f'No images staged from {args.dataset}'
        logger.info('Staged %d images from cameras: %s', expected_count,
                    ', '.join(c or '<root>' for c in cameras))

        module = PreprocessImages(logger)
        params = module.get_parameters()
        params['output_dir'] = Parameter('Output Directory', 'o', 'output_dir', str, work_dir)
        params['pre_input_image_dir'].set_value(input_dir)
        module.set_params(params)

        ok, message = module.validate_parameters()
        assert ok, message

        result = module.run()
        module.finish()
        assert result['Success'], result
        assert result['Processed'] == expected_count, result
        assert result['Failed'] == 0, result

        out_dir = result['Output Directory']
        for cam in cameras:
            src = os.path.join(input_dir, cam) if cam else input_dir
            dst = os.path.join(out_dir, cam) if cam else out_dir
            assert set(os.listdir(src)) == set(os.listdir(dst)), \
                f'{cam or "<root>"}: filenames not preserved'
        print('folder mirroring + filename preservation: OK')

        # Byte parity with the canonical transform at the module's own
        # encoder settings - guards against testing/ and the pipeline
        # diverging into two implementations.
        first_cam = cameras[0]
        cam_in = os.path.join(input_dir, first_cam) if first_cam else input_dir
        cam_out = os.path.join(out_dir, first_cam) if first_cam else out_dir
        sample = sorted(os.listdir(cam_in))[0]

        transform = build_transform({'clahe_clip': 2.0, 'clahe_tile': 8})
        expected = transform(cv2.imread(os.path.join(cam_in, sample)))
        encoded, buffer = cv2.imencode('.jpg', expected, [cv2.IMWRITE_JPEG_QUALITY, 95])
        assert encoded
        with open(os.path.join(cam_out, sample), 'rb') as f:
            assert buffer.tobytes() == f.read(), 'module output differs from canonical transform'
        print('byte parity with canonical transform: OK')

        rerun = module.run()
        module.finish()
        assert rerun['Processed'] == 0 and rerun['Skipped (already done)'] == expected_count, rerun
        print('idempotent rerun (all skipped): OK')

        original = cv2.imread(os.path.join(cam_in, sample))
        processed = cv2.imread(os.path.join(cam_out, sample))
        assert original.shape == processed.shape
        mean_delta = np.abs(original.astype(int) - processed.astype(int)).mean()
        assert mean_delta > 1, f'CLAHE barely changed the image (mean delta {mean_delta:.3f})'
        print(f'CLAHE altered pixels (mean delta {mean_delta:.1f}): OK')

        print('ALL PREPROCESS MODULE TESTS PASSED')
    finally:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == '__main__':
    main()
