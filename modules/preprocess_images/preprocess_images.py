"""Pre-alignment image preprocessing for underwater imagery.

Canonical implementation of the CLAHE / white-balance transforms; the
testing variants (testing/preprocess_variants.py) import from here rather
than maintaining their own copy.

Defaults (CLAHE clip 2.0, 8x8 tiles, no white balance) come from the
2026-07-21 zone_9 A/B iteration (testing/run_zone9_tests.py phase 2):
baseline registered 0/400 images (alignment produced no component at
all), CLAHE 2.0/8x8 registered 59.8%, every neighboring clip/tile setting
scored lower, and adding gray-world white balance dropped registration to
~34%. See rs_cli_tests/REPORT.md from that run.

Originals are never modified: processed copies are written to
<output_dir>/preprocessed_images with the input's folder structure and the
same filenames (flight-log matching relies on the names). Align on the
processed copies; keep the originals for texturing.
"""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor

import cv2
import numpy as np

from module_base.rs_module import RSModule
from module_base.parameter import Parameter

IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png')
JPEG_QUALITY = 95


def gray_world_white_balance(img: np.ndarray) -> np.ndarray:
    result = img.astype(np.float32)
    means = result.reshape(-1, 3).mean(axis=0)
    overall = means.mean()
    for c in range(3):
        if means[c] > 1e-6:
            result[:, :, c] *= overall / means[c]
    return np.clip(result, 0, 255).astype(np.uint8)


def clahe_lab(img: np.ndarray, clip: float, tile: int) -> np.ndarray:
    """CLAHE on the L channel in LAB space: enhances local contrast without
    shifting color, which is what matters for feature matching on
    underwater imagery."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=clip, tileGridSize=(tile, tile))
    l_channel = clahe.apply(l_channel)
    return cv2.cvtColor(cv2.merge((l_channel, a_channel, b_channel)), cv2.COLOR_LAB2BGR)


def build_transform(params: dict):
    """Returns a BGR->BGR callable for these parameters, or None when no
    step is enabled (= byte-for-byte copy)."""
    steps = []
    if params.get('white_balance'):
        steps.append(gray_world_white_balance)
    if params.get('clahe_clip'):
        clip = float(params['clahe_clip'])
        tile = int(params.get('clahe_tile', 8))
        steps.append(lambda img, c=clip, t=tile: clahe_lab(img, c, t))

    if not steps:
        return None

    def transform(img):
        for step in steps:
            img = step(img)
        return img

    return transform


def _process_one(job: tuple[str, str, float, int, bool]) -> str | None:
    """Worker: read src, apply the transform, write dst. Returns the source
    path on failure so the parent can log it (module methods are not
    picklable, so this is a top-level function rebuilding the transform)."""
    src, dst, clahe_clip, clahe_tile, white_balance = job
    transform = build_transform({'clahe_clip': clahe_clip,
                                 'clahe_tile': clahe_tile,
                                 'white_balance': white_balance})
    image = cv2.imread(src, cv2.IMREAD_COLOR)
    if image is None:
        return src
    if transform is not None:
        image = transform(image)
    if not cv2.imwrite(dst, image, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]):
        return src
    return None


class PreprocessImages(RSModule):

    def __init__(self, logger):
        super().__init__("Preprocess Images", logger)

    def get_parameters(self) -> dict[str, Parameter]:
        additional_params = {}

        additional_params['pre_input_image_dir'] = Parameter(
            name='Preprocess Input Folder',
            cli_short='p_i',
            cli_long='p_input',
            type=str,
            default_value=None,
            description='Directory containing the images to preprocess',
            prompt_user=True,
            disable_when_module_active='Extract Images'
        )

        additional_params['pre_clahe_clip'] = Parameter(
            name='CLAHE Clip Limit',
            cli_short='p_c',
            cli_long='p_clahe_clip',
            type=float,
            default_value=2.0,
            description='CLAHE clip limit (0 disables CLAHE; 2.0 won the zone_9 A/B)',
            prompt_user=False
        )

        additional_params['pre_clahe_tile'] = Parameter(
            name='CLAHE Tile Size',
            cli_short='p_t',
            cli_long='p_clahe_tile',
            type=int,
            default_value=8,
            description='CLAHE tile grid size (NxN)',
            prompt_user=False
        )

        additional_params['pre_white_balance'] = Parameter(
            name='Gray-World White Balance',
            cli_short='p_wb',
            cli_long='p_white_balance',
            type=bool,
            default_value=False,
            description='Apply gray-world white balance before CLAHE (hurt registration in the zone_9 A/B - off by default)',
            prompt_user=False
        )

        additional_params['pre_workers'] = Parameter(
            name='Preprocess Workers',
            cli_short='p_w',
            cli_long='p_workers',
            type=int,
            default_value=0,
            description='Parallel worker processes (0 = cpu count)',
            prompt_user=False
        )

        return {**super().get_parameters(), **additional_params}

    def __get_input_dir(self) -> str:
        if 'pre_input_image_dir' in self.params:
            return self.params['pre_input_image_dir'].get_value()
        return os.path.join(self.params['output_dir'].get_value(), 'raw_images')

    def get_output_dir(self) -> str:
        return os.path.join(self.params['output_dir'].get_value(), 'preprocessed_images')

    def __collect_jobs(self, input_dir: str, output_dir: str,
                       clip: float, tile: int, wb: bool):
        """One (src, dst, ...) job per image, mirroring the input's folder
        structure. Existing outputs are skipped so an interrupted run can
        resume."""
        jobs = []
        skipped = 0
        for root, _dirs, files in os.walk(input_dir):
            rel = os.path.relpath(root, input_dir)
            dest_root = output_dir if rel == '.' else os.path.join(output_dir, rel)
            for name in files:
                if not name.lower().endswith(IMAGE_EXTENSIONS):
                    continue
                dst = os.path.join(dest_root, name)
                if os.path.exists(dst):
                    skipped += 1
                    continue
                os.makedirs(dest_root, exist_ok=True)
                jobs.append((os.path.join(root, name), dst, clip, tile, wb))
        return jobs, skipped

    def run(self):
        input_dir = self.__get_input_dir()
        output_dir = self.get_output_dir()
        clip = float(self.params['pre_clahe_clip'].get_value())
        tile = int(self.params['pre_clahe_tile'].get_value())
        wb = bool(self.params['pre_white_balance'].get_value())
        # ProcessPoolExecutor on Windows caps max_workers at 61
        workers = min(int(self.params['pre_workers'].get_value()) or os.cpu_count() or 1, 61)

        if not clip and not wb:
            self.logger.warning('No preprocessing steps enabled (clip=0, white balance off) - nothing to do')
            return {'Success': False}

        os.makedirs(output_dir, exist_ok=True)
        jobs, skipped = self.__collect_jobs(input_dir, output_dir, clip, tile, wb)
        self.logger.info('Preprocessing %d images (%d already done) with CLAHE clip=%g tile=%dx%d wb=%s',
                         len(jobs), skipped, clip, tile, tile, wb)

        failures = []
        if jobs:
            bar = self._initialize_loading_bar(len(jobs), 'Preprocessing Images')
            with ProcessPoolExecutor(max_workers=workers) as pool:
                for failed_src in pool.map(_process_one, jobs, chunksize=16):
                    if failed_src:
                        failures.append(failed_src)
                    self._update_loading_bar(bar, 1)

        for src in failures[:10]:
            self.logger.warning('Unreadable or unwritable image skipped: %s', src)
        if len(failures) > 10:
            self.logger.warning('...and %d more failures', len(failures) - 10)

        return {
            'Success': True,
            'Processed': len(jobs) - len(failures),
            'Skipped (already done)': skipped,
            'Failed': len(failures),
            'CLAHE': f'clip {clip:g}, {tile}x{tile} tiles' if clip else 'off',
            'White Balance': wb,
            'Output Directory': output_dir,
        }

    def validate_parameters(self) -> tuple[bool, str | None]:
        success, message = super().validate_parameters()
        if not success:
            return success, message

        input_dir = self.__get_input_dir()
        # When chained after Extract Images the input folder is produced at
        # runtime, so only validate an explicitly given directory.
        if 'pre_input_image_dir' in self.params and not os.path.isdir(input_dir):
            return False, f'Preprocess input directory does not exist: {input_dir}'

        clip = float(self.params['pre_clahe_clip'].get_value())
        if clip < 0:
            return False, 'CLAHE clip limit must be >= 0'
        tile = int(self.params['pre_clahe_tile'].get_value())
        if tile < 1:
            return False, 'CLAHE tile size must be >= 1'

        return True, None
