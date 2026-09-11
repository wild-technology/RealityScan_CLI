"""Conservative, read-only local-detail screening; never a semantic water detector.

The controller owns inventory selection, exclusions and user overrides. This
module only assesses one image and optionally writes derived review artifacts.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import tempfile

import cv2
import numpy as np


ALGORITHM_VERSION = 'local-detail-3'


@dataclass(frozen=True)
class ScreeningThresholds:
    """Normalized intensity thresholds at a common analysis resolution.

    These are conservative engineering starting values, not field-calibrated
    reconstruction thresholds. Project overrides must be recorded by callers.
    """
    analysis_long_edge: int = 768
    grid_size: int = 8
    contrast_floor: float = 0.006
    gradient_floor: float = 0.001
    structure_fraction: float = 0.015
    structure_span: float = 0.18
    min_corners: int = 3
    corner_quality: float = 0.02
    min_valid_fraction: float = 0.25
    min_tile_valid_fraction: float = 0.20
    min_analysis_coverage: float = 0.90
    edge_band_fraction: float = 0.10
    diagnostic_clahe: bool = False

    def validate(self) -> None:
        for name, lo, hi in [('analysis_long_edge', 256, 1536),
                             ('grid_size', 4, 16), ('min_corners', 1, 64)]:
            value = getattr(self, name)
            if type(value) is not int or not lo <= value <= hi:
                raise ValueError(f'{name} must be an integer in [{lo}, {hi}]')
        for name in ('contrast_floor', 'gradient_floor', 'structure_fraction',
                     'structure_span', 'corner_quality', 'min_valid_fraction',
                     'min_tile_valid_fraction', 'min_analysis_coverage'):
            value = getattr(self, name)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or not 0 < value <= 1):
                raise ValueError(f'{name} must be finite and in (0, 1]')
        if type(self.diagnostic_clahe) is not bool:
            raise ValueError('diagnostic_clahe must be boolean')
        if (isinstance(self.edge_band_fraction, bool) or not isinstance(self.edge_band_fraction, (int, float))
                or not math.isfinite(self.edge_band_fraction) or not 0 <= self.edge_band_fraction <= 0.25):
            raise ValueError('edge_band_fraction must be finite and in [0, 0.25]')


def _read(path: Path) -> tuple[bytes, str]:
    before = path.stat()
    content = path.read_bytes()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f'input changed while being read: {path}')
    return content, hashlib.sha256(content).hexdigest()


def _decode(content: bytes, label: str) -> np.ndarray:
    decoded = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_UNCHANGED)
    if decoded is None or decoded.size == 0:
        raise ValueError(f'cannot decode {label}')
    if decoded.dtype not in (np.uint8, np.uint16):
        raise ValueError(f'{label} must use uint8 or uint16 samples')
    return decoded


def _prepare(image: np.ndarray, mask: np.ndarray | None, t: ScreeningThresholds):
    h, w = image.shape[:2]
    if min(h, w) < 32 or max(h, w) / min(h, w) > 8:
        raise ValueError('image is too small or narrow for local-detail assessment')
    valid = np.ones((h, w), np.uint8)
    if mask is not None:
        if mask.ndim != 2 or mask.shape != (h, w):
            raise ValueError('mask must be single-channel and match the image dimensions')
        values = set(np.unique(mask).tolist())
        maximum = int(np.iinfo(mask.dtype).max)
        if not (values <= {0, 1} or values <= {0, maximum}):
            raise ValueError('mask must be binary: zero excludes, nonzero includes')
        valid = (mask != 0).astype(np.uint8)
    samples = image.astype(np.float32) / np.iinfo(image.dtype).max
    if image.ndim == 2:
        gray = samples
        bgr = cv2.cvtColor(samples, cv2.COLOR_GRAY2BGR)
    elif image.ndim == 3 and image.shape[2] in (3, 4):
        bgr = samples[:, :, :3]
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        if image.shape[2] == 4:
            valid &= (image[:, :, 3] != 0).astype(np.uint8)
    else:
        raise ValueError('unsupported image channels')
    scale = t.analysis_long_edge / max(h, w)
    size = (round(w * scale), round(h * scale))
    interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    gray = cv2.resize(gray, size, interpolation=interpolation)
    bgr = cv2.resize(bgr, size, interpolation=interpolation)
    valid = cv2.resize(valid, size, interpolation=cv2.INTER_NEAREST)
    # Erosion excludes mask-boundary gradients, including support of the coarse
    # blur and corner detector. The mask itself never becomes image texture.
    inner = cv2.erode(valid, np.ones((17, 17), np.uint8),
                      borderType=cv2.BORDER_CONSTANT, borderValue=0)
    return gray, bgr, valid, inner


def _corners(gray: np.ndarray, valid: np.ndarray, t: ScreeningThresholds) -> int:
    found = cv2.goodFeaturesToTrack(np.ascontiguousarray(gray, dtype=np.float32),
                                    maxCorners=128, qualityLevel=t.corner_quality,
                                    minDistance=4, mask=valid.astype(np.uint8) * 255,
                                    blockSize=3, useHarrisDetector=False)
    return 0 if found is None else len(found)


def _tile(gray, coarse, gradient, valid, bounds, t):
    x0, y0, x1, y1 = bounds
    local = valid[y0:y1, x0:x1].astype(bool)
    n = int(local.sum())
    result = {'bounds': list(bounds), 'valid_pixels': n,
              'valid_fraction': float(local.mean()), 'state': 'unassessed'}
    if n < 64 or local.mean() < t.min_tile_valid_fraction:
        return result
    raw = gray[y0:y1, x0:x1]
    smooth = coarse[y0:y1, x0:x1]
    grad = gradient[y0:y1, x0:x1]
    # Percentile contrast and an absolute gradient floor prevent relative GFTT
    # from promoting the strongest corner in almost-uniform noise to evidence.
    contrast = float(np.percentile(smooth[local], 99) - np.percentile(smooth[local], 1))
    raw_contrast = float(np.percentile(raw[local], 99) - np.percentile(raw[local], 1))
    raw_range = float(np.ptp(raw[local]))
    strong = (grad >= t.gradient_floor) & local
    structure = float(strong.sum() / n)
    _, _, stats, _ = cv2.connectedComponentsWithStats(strong.astype(np.uint8), 8)
    spans = [math.hypot(int(s[cv2.CC_STAT_WIDTH]), int(s[cv2.CC_STAT_HEIGHT]))
             / math.hypot(x1 - x0, y1 - y0)
             for s in stats[1:] if s[cv2.CC_STAT_AREA] >= 8]
    span = max(spans, default=0.0)
    corners = _corners(smooth, local, t)
    raw_corners = _corners(raw, local, t)
    meaningful = (contrast >= t.contrast_floor and structure >= t.structure_fraction
                  and (span >= t.structure_span or corners >= t.min_corners))
    # Do not call isolated or weak conflicting detail water. A conservative
    # uncertainty veto avoids turning removed backscatter into a cull decision.
    uncertain = not meaningful and (
        raw_range >= t.contrast_floor or
        (raw_corners >= t.min_corners and raw_contrast >= t.contrast_floor / 2))
    state = 'textured_patch' if meaningful else 'uncertain_detail' if uncertain else 'low_texture'
    result.update(state=state, contrast=contrast, raw_contrast=raw_contrast, raw_range=raw_range,
                  gradient_p95=float(np.percentile(grad[local], 95)),
                  structure_fraction=structure, structure_span=span,
                  corners=corners, raw_corners=raw_corners)
    return result


def _analyze(gray, valid, inner, t):
    # No equalization or per-image min/max stretching enters the decision.
    median = cv2.medianBlur(gray, 3)
    coarse = cv2.GaussianBlur(median, (13, 13), 2.0)
    dx = cv2.Sobel(coarse, cv2.CV_32F, 1, 0, ksize=3, scale=1 / 8)
    dy = cv2.Sobel(coarse, cv2.CV_32F, 0, 1, ksize=3, scale=1 / 8)
    gradient = cv2.magnitude(dx, dy)
    height, width = gray.shape
    xs = np.linspace(0, width, t.grid_size + 1, dtype=int)
    ys = np.linspace(0, height, t.grid_size + 1, dtype=int)
    tiles, grid, covered = [], [], np.zeros_like(valid)
    for row in range(t.grid_size):
        cells = []
        for col in range(t.grid_size):
            bounds = (int(xs[col]), int(ys[row]), int(xs[col + 1]), int(ys[row + 1]))
            tile = _tile(gray, coarse, gradient, inner, bounds, t)
            cells.append(len(tiles))
            tiles.append(dict(tile, row=row, column=col, offset=False))
        grid.append(cells)
    # Half-tile offsets protect a small useful patch crossing four grid cells.
    for row in range(t.grid_size - 1):
        for col in range(t.grid_size - 1):
            bounds = (int((xs[col] + xs[col + 1]) // 2),
                      int((ys[row] + ys[row + 1]) // 2),
                      int((xs[col + 1] + xs[col + 2]) // 2),
                      int((ys[row + 1] + ys[row + 2]) // 2))
            tile = _tile(gray, coarse, gradient, inner, bounds, t)
            tiles.append(dict(tile, row=row, column=col, offset=True))
    for tile in tiles:
        if tile['state'] != 'unassessed':
            x0, y0, x1, y1 = tile['bounds']
            covered[y0:y1, x0:x1] |= inner[y0:y1, x0:x1]
    counts = {state: sum(tile['state'] == state for tile in tiles)
              for state in ('textured_patch', 'uncertain_detail', 'low_texture', 'unassessed')}
    # Include support lost to mask erosion in the denominator. Otherwise a
    # fragmented mask could erase almost all detail yet certify full coverage.
    coverage = float(covered.sum() / max(int(valid.sum()), 1))
    valid_fraction = float(valid.mean())
    # Edge-only texture can be equipment OR useful scene. Retain for review;
    # never strip those pixels or infer a semantic hardware/water label.
    # Reuse the local detector inside the border instead of letting a whole
    # edge tile's bounding box pretend its texture extends into the interior.
    edge_x, edge_y = round(width * t.edge_band_fraction), round(height * t.edge_band_fraction)
    halo = 6 if t.edge_band_fraction else 0  # Gaussian support cannot leak border detail inward.
    interior_bounds = [edge_x + halo, edge_y + halo, width - edge_x - halo, height - edge_y - halo]
    interior_textured = 0
    for tile in tiles:
        if tile['state'] != 'textured_patch':
            continue
        x0, y0, x1, y1 = tile['bounds']
        bounds = (max(x0, interior_bounds[0]), max(y0, interior_bounds[1]),
                  min(x1, interior_bounds[2]), min(y1, interior_bounds[3]))
        state = 'unassessed'
        if bounds[2] - bounds[0] >= 8 and bounds[3] - bounds[1] >= 8:
            state = _tile(gray, coarse, gradient, inner, bounds, t)['state']
        tile['interior_state'] = state
        interior_textured += state == 'textured_patch'
    if (not inner.any() or valid_fraction < t.min_valid_fraction
          or coverage < t.min_analysis_coverage):
        decision, reason = 'review_required', 'insufficient_unmasked_support'
    elif counts['textured_patch'] and not interior_textured:
        decision, reason = 'review_required', 'edge_only_detail_uncertain'
    elif counts['textured_patch']:
        decision, reason = 'keep', 'meaningful_textured_patch'
    elif counts['uncertain_detail']:
        decision, reason = 'review_required', 'sparse_or_weak_detail_uncertain'
    else:
        decision, reason = 'candidate', 'low_texture_candidate'
    metrics = dict(valid_fraction=valid_fraction, analysis_coverage=coverage,
                   tile_counts=counts, analysis_width=width, analysis_height=height,
                   interior_textured_tiles=interior_textured, interior_bounds=interior_bounds)
    if t.diagnostic_clahe:
        enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(
            np.rint(gray * 255).astype(np.uint8))
        metrics['diagnostic_clahe_corners'] = _corners(enhanced / np.float32(255), inner, t)
    return decision, reason, metrics, tiles, grid


def _artifacts(result, bgr, artifact_dir, image_path, mask_path):
    root = Path(artifact_dir).resolve()
    # The caller owns proc/tmp. Refuse an obvious source-folder destination;
    # broader project ownership checks remain the controller's responsibility.
    for source in (image_path, mask_path):
        if source is not None and root.is_relative_to(source.parent.resolve()):
            raise ValueError('review artifacts must be outside image/mask source folders')
    root.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix=result['assessment_fingerprint'][:12] + '_', dir=root))
    view = np.rint(np.clip(bgr, 0, 1) * 255).astype(np.uint8)
    overlay = view.copy()
    colors = {'textured_patch': (30, 190, 30), 'uncertain_detail': (0, 200, 255),
              'low_texture': (40, 40, 200), 'unassessed': (120, 120, 120)}
    for tile in result['tiles']:
        x0, y0, x1, y1 = tile['bounds']
        if not tile['offset']:
            cv2.rectangle(overlay, (x0, y0), (x1 - 1, y1 - 1), colors[tile['state']], -1)
    heatmap = cv2.addWeighted(view, 0.65, overlay, 0.35, 0)
    for tile in result['tiles']:
        if tile['state'] == 'textured_patch':
            x0, y0, x1, y1 = tile['bounds']
            cv2.rectangle(heatmap, (x0, y0), (x1 - 1, y1 - 1), (30, 240, 30), 1)
    if result['reason'] == 'edge_only_detail_uncertain':
        x0, y0, x1, y1 = result['metrics']['interior_bounds']
        cv2.rectangle(heatmap, (x0, y0), (x1 - 1, y1 - 1), (0, 165, 255), 2)
    ratio = min(1.0, 384 / max(view.shape[:2]))
    thumbnail = cv2.resize(view, (round(view.shape[1] * ratio), round(view.shape[0] * ratio)))
    for label, data in [('thumbnail', thumbnail), ('heatmap', heatmap)]:
        path = out / f'{label}.jpg'
        ok, encoded = cv2.imencode('.jpg', data, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            raise OSError(f'cannot encode {label}')
        path.write_bytes(encoded.tobytes())
        result[f'{label}_path'] = str(path)
    result['report_path'] = str(out / 'assessment.json')
    Path(result['report_path']).write_text(json.dumps(result, indent=2, allow_nan=False), encoding='utf-8')


def assess_image(image_path: str | Path, *, mask_path: str | Path | None = None,
                 thresholds: ScreeningThresholds | None = None,
                 artifact_dir: str | Path | None = None) -> dict:
    """Assess original pixels; return keep/candidate/review_required, never exclude.

    Mask: single-channel, same dimensions, binary; white/nonzero is valid.
    Artifacts are optional and must be directed to caller-owned proc/tmp.
    Bad inputs return review_required. Bad threshold configuration raises.
    No override or inclusion state is persisted; the controller owns those.
    """
    t = thresholds or ScreeningThresholds()
    t.validate()
    path = Path(image_path).resolve()
    mask_file = Path(mask_path).resolve() if mask_path is not None else None
    result = dict(schema_version=1, algorithm_version=ALGORITHM_VERSION,
                  image_path=str(path), mask_path=str(mask_file) if mask_file else None,
                  image_sha256=None, mask_sha256=None, thresholds=asdict(t),
                  engine={'opencv': cv2.__version__, 'numpy': np.__version__},
                  decision='review_required', reason='input_unassessed', candidate=False,
                  assessment_complete=False, exclusion_requires_confirmation=True,
                  metrics={}, tiles=[], tile_grid=[], thumbnail_path=None,
                  heatmap_path=None, report_path=None, errors=[],
                  limitations=['Local detail is not semantic water/seafloor ground truth.',
                               'Detail does not prove overlap or reconstruction value.',
                               'Defaults and synthetic tests are not field validation.'])
    bgr = None
    try:
        content, result['image_sha256'] = _read(path)
        image = _decode(content, 'image')
        mask = None
        if mask_file is not None:
            content, result['mask_sha256'] = _read(mask_file)
            mask = _decode(content, 'mask')
        gray, bgr, valid, inner = _prepare(image, mask, t)
        decision, reason, metrics, tiles, grid = _analyze(gray, valid, inner, t)
        result.update(decision=decision, reason=reason, candidate=decision == 'candidate',
                      assessment_complete=True, metrics=metrics, tiles=tiles, tile_grid=grid,
                      source_dimensions=[int(image.shape[1]), int(image.shape[0])])
    except (OSError, ValueError, cv2.error) as exc:
        result['errors'].append(str(exc))
    fingerprint = {k: result[k] for k in ('algorithm_version', 'image_sha256', 'mask_sha256',
                                         'thresholds', 'engine')}
    fingerprint['mask_requested'] = mask_file is not None
    result['assessment_fingerprint'] = hashlib.sha256(json.dumps(
        fingerprint, sort_keys=True, allow_nan=False).encode()).hexdigest()
    if artifact_dir is not None and bgr is not None and result['assessment_complete']:
        try:
            _artifacts(result, bgr, artifact_dir, path, mask_file)
        except (OSError, ValueError, cv2.error) as exc:
            result['errors'].append(f'review artifacts unavailable: {exc}')
    return result
