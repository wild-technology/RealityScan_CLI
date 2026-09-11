"""Optional POST-BATCH temporal ROV-fringe evidence, never automatic masking.

Unregistered frames from one camera/extent are sampled deterministically. Only
stable, locally textured, edge-connected fringe regions become candidates.
Motion guards reduce stationary-scene risk; this is not semantic recognition.
The controller owns optional enablement, review, batch lifetime and sidecar copy.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import tempfile

import cv2
import numpy as np
from PIL import Image

from .image_quality import _decode, _read
from .project_reviews import digest, write_json


VERSION = 'temporal-occlusion-2'
MAX_PIXELS = 89_478_485


@dataclass(frozen=True)
class TemporalFrame:
    path: str | Path
    sha256: str
    camera: str
    family: str
    timestamp_utc: str
    # Caller supplies a verified sensor/crop/orientation identity, not just size.
    frame_extent: str
    width: int
    height: int
    registered: bool = False


@dataclass(frozen=True)
class TemporalMaskConfig:
    sample_count: int = 96
    analysis_long_edge: int = 384
    min_samples: int = 24
    min_span_seconds: float = 120.0
    fringe_fraction: float = .18
    temporal_range_max: float = .08
    detail_threshold: float = .012
    structure_window: int = 9
    structure_min_correlation: float = .40
    structure_median_correlation: float = .85
    structure_std_floor: float = .02
    growth_pixels: int = 12
    shape_close_pixels: int = 3
    exposure_residual_max: float = .10
    motion_pixel_threshold: float = .045
    min_motion_fraction: float = .15
    min_moving_pairs_fraction: float = .60
    max_center_correlation: float = .85
    min_center_detail_fraction: float = .03
    max_candidate_fraction: float = .20
    min_component_pixels: int = 24
    block_seconds: int = 900

    def validate(self):
        for rule in parameter_schema():
            name = rule['key']
            value = getattr(self, name)
            if rule['type'] == 'int':
                if type(value) is not int or not rule['min'] <= value <= rule['max']:
                    raise ValueError(f'{name} must be an integer in [{rule["min"]}, {rule["max"]}]')
                if (value-rule['min']) % rule['step']:
                    raise ValueError(f'{name} must use step {rule["step"]} from {rule["min"]}')
            elif (isinstance(value, bool) or not isinstance(value, (int, float))
                  or not math.isfinite(value) or not rule['min'] <= value <= rule['max']):
                raise ValueError(f'{name} must be finite and in [{rule["min"]}, {rule["max"]}]')
        if self.min_samples > self.sample_count:
            raise ValueError('min_samples cannot exceed sample_count')
        if self.structure_min_correlation > self.structure_median_correlation:
            raise ValueError('Minimum structure correlation exceeds median threshold')


def parameter_schema():
    """Single constraints source for validate() and controller/GUI spinboxes.
    Cross-field rules remain in validate; parameters and defaults are proposals.
    """
    integers = {'sample_count': (4, 256, 1, 'frames'), 'min_samples': (4, 256, 1, 'frames'),
                'analysis_long_edge': (128, 1024, 1, 'pixels'),
                'min_component_pixels': (1, 10000, 1, 'analysis pixels'),
                'block_seconds': (60, 3600, 1, 'seconds'),
                'structure_window': (5, 31, 2, 'analysis pixels'),
                'growth_pixels': (0, 24, 1, 'analysis pixels'),
                'shape_close_pixels': (1, 7, 2, 'analysis pixels')}
    ranges = {'min_span_seconds': (.001, 86400*365, 'seconds'),
              'fringe_fraction': (.000001, .30, 'fraction of width/height'),
              'max_candidate_fraction': (.000001, .40, 'fraction of image')}
    result = []
    for name, default in asdict(TemporalMaskConfig()).items():
        if name in integers:
            lo, hi, step, units = integers[name]
            kind = 'int'
        else:
            lo, hi, units = ranges.get(name, (.000001, 1., 'normalized fraction'))
            step, kind = .001, 'float'
        result.append(dict(key=name, label=name.replace('_', ' ').capitalize(), type=kind,
                           min=lo, max=hi, step=step, default=default, units=units,
                           decimals=0 if kind == 'int' else 6))
    return result


def _sha(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('Expected lowercase SHA-256')
    return value


def _utc(value):
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('UTC offset required')
        return stamp.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError('Valid timezone-aware frame timestamp required') from exc


def _cancel(cancelled):
    if cancelled is not None and cancelled():
        raise InterruptedError('Temporal occlusion assessment cancelled')


def _header(content):
    with Image.open(io.BytesIO(content)) as image:
        width, height = image.size
        if width * height > MAX_PIXELS or min(width, height) < 32 or max(width, height) / min(width, height) > 8:
            raise ValueError('Unsupported frame extent/dimensions')
        if getattr(image, 'n_frames', 1) != 1:
            raise ValueError('Multiple-frame images are not supported')
        # Never silently rotate some frames but not others.
        orientation = image.getexif().get(274, 1)
        if orientation != 1:
            raise ValueError('Nonidentity EXIF orientation needs an explicit normalized frame set')
    return width, height


def _pixels(frame):
    content, sha = _read(Path(frame.path))
    if sha != frame.sha256:
        raise ValueError(f'Frame content changed: {frame.path}')
    width, height = _header(content)
    if (width, height) != (frame.width, frame.height):
        raise ValueError('Frame differs from inventoried dimensions')
    image = _decode(content, 'temporal frame')
    if image.shape[:2] != (height, width):
        raise ValueError('Decoded frame differs from header dimensions')
    if image.ndim == 2:
        gray = image
    elif image.ndim == 3 and image.shape[2] == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        raise ValueError('Temporal frames require grayscale or RGB without alpha')
    return gray.astype(np.float32) / np.iinfo(gray.dtype).max, (width, height, str(image.dtype))


def select_temporal_samples(frames, config):
    """Time-quantile indices round(k*(n-1)/(N-1)); collapse equal hashes first.
    Sorting and camera/extent checks cover ALL supplied frames, not just samples.
    """
    config.validate()
    frames = list(frames)
    if not frames:
        raise ValueError('No frames supplied')
    identities, paths, canonical = set(), set(), {}
    for frame in frames:
        if not isinstance(frame, TemporalFrame):
            raise TypeError('frames must contain TemporalFrame records')
        _sha(frame.sha256)
        if any(not isinstance(v, str) or not v.strip() for v in (frame.camera, frame.family, frame.frame_extent)):
            raise ValueError('Explicit camera, family and frame_extent required')
        if any(type(v) is not int or v < 32 for v in (frame.width, frame.height)) or frame.width*frame.height > MAX_PIXELS:
            raise ValueError('Valid inventoried frame dimensions required')
        if type(frame.registered) is not bool or frame.registered:
            raise ValueError('Registered frames cannot establish camera-fixed occlusion')
        stamp = _utc(frame.timestamp_utc)
        path = str(Path(frame.path).resolve(strict=True))
        if path.casefold() in paths:
            raise ValueError('Duplicate input path')
        paths.add(path.casefold())
        identities.add((frame.camera, frame.family, frame.frame_extent, frame.width, frame.height))
        key = (stamp, path, frame.sha256)
        if frame.sha256 not in canonical or key < canonical[frame.sha256][0]:
            canonical[frame.sha256] = (key, frame)
    if len(identities) != 1:
        raise ValueError('Mixed camera/family/frame extent; assess separate groups')
    ordered = [pair[1] for pair in sorted(canonical.values(), key=lambda p: p[0])]
    count = min(config.sample_count, len(ordered))
    indices = [round(k * (len(ordered) - 1) / (count - 1)) for k in range(count)] if count > 1 else [0]
    return [ordered[i] for i in indices], len(ordered)


def canonical_image_id(frame):
    """Zone/path-independent identity; the same camera content gets one mask."""
    return digest([frame.camera, frame.family, frame.frame_extent, frame.width, frame.height, _sha(frame.sha256)])


def plan_temporal_blocks(frames, *, block_seconds=900):
    """Plan ONCE over the complete retained inventory, never per-zone subsets.

    Fixed UTC boundaries make tilt/time domains explicit. Output members use
    canonical image IDs; overlapping zones must look up the same assignment.
    Identical camera content with conflicting timestamps is ambiguous and fails.
    """
    if type(block_seconds) is not int or not 60 <= block_seconds <= 3600:
        raise ValueError('block_seconds must be an integer in [60, 3600]')
    canonical = {}
    for frame in frames:
        # Shared validation, including timezone, dimensions and registration.
        select_temporal_samples([frame], TemporalMaskConfig())
        image_id = canonical_image_id(frame)
        stamp = _utc(frame.timestamp_utc)
        if image_id in canonical and _utc(canonical[image_id].timestamp_utc) != stamp:
            raise ValueError('Same image identity has conflicting timestamps')
        if image_id not in canonical or str(frame.path) < str(canonical[image_id].path):
            canonical[image_id] = frame
    groups = {}
    for image_id, frame in sorted(canonical.items()):
        start = math.floor(_utc(frame.timestamp_utc).timestamp() / block_seconds) * block_seconds
        domain = dict(camera=frame.camera, family=frame.family, frame_extent=frame.frame_extent,
                      width=frame.width, height=frame.height, start_unix=start, block_seconds=block_seconds)
        block_id = digest(dict(version=VERSION, **domain))
        group = groups.setdefault(block_id, dict(block_id=block_id, **domain, members=[]))
        member = asdict(frame)
        member['path'] = str(Path(frame.path).resolve())
        member['image_id'] = image_id
        group['members'].append(member)
    for group in groups.values():
        group['membership_hash'] = digest([m['image_id'] for m in group['members']])
    return sorted(groups.values(), key=lambda g: (g['start_unix'], g['block_id']))


def _runs(mask):
    flat = mask.ravel().astype(np.int8)
    changes = np.diff(np.concatenate(([0], flat, [0])))
    return [[int(a), int(b - a)] for a, b in zip(np.flatnonzero(changes == 1), np.flatnonzero(changes == -1))]


def _analyze(stack, config, *, cancelled=None, progress=None):
    """Pure bounded-resolution calculation; all frames remain unregistered."""
    n, h, w = stack.shape
    # Central field must change substantially, not only through exposure shifts.
    y, x = max(1, int(h * .30)), max(1, int(w * .30))
    core = stack[:, y:h-y, x:w-x]
    core = core - np.median(core, axis=(1, 2), keepdims=True)
    motion = np.mean(np.abs(np.diff(core, axis=0)) > config.motion_pixel_threshold, axis=(1, 2)) if n > 1 else np.zeros(1)
    correlations = []
    for a, b in zip(core[:-1], core[1:]):
        aa, bb = a.ravel().astype(np.float64), b.ravel().astype(np.float64)
        aa -= aa.mean()
        bb -= bb.mean()
        denominator = float(np.linalg.norm(aa) * np.linalg.norm(bb))
        correlations.append(float(np.dot(aa, bb) / denominator) if denominator > 1e-9 else 1.0)
    details = []
    for frame in stack:
        _cancel(cancelled)
        details.append(np.abs(frame - cv2.GaussianBlur(frame, (5, 5), 0)))
    details = np.stack(details)
    center_detail = float(np.mean(details[:, y:h-y, x:w-x] >= config.detail_threshold))
    fringe = np.zeros((h, w), np.uint8)
    fy, fx = max(1, round(h * config.fringe_fraction)), max(1, round(w * config.fringe_fraction))
    fringe[:fy] = fringe[-fy:] = 1
    fringe[:, :fx] = fringe[:, -fx:] = 1
    # Local normalized correlation preserves spatial structure under changing
    # lighting. No image registration, local warping or mask outline is used.
    reference = np.median(stack, axis=0)
    def box(pixels):
        return cv2.boxFilter(pixels, -1, (config.structure_window, config.structure_window),
                             normalize=True, borderType=cv2.BORDER_REFLECT)
    reference_mean = box(reference)
    reference_variance = np.maximum(box(reference*reference)-reference_mean**2, 0)
    structure = []
    for done, frame in enumerate(stack, 1):
        _cancel(cancelled)
        mean = box(frame)
        variance = np.maximum(box(frame*frame)-mean**2, 0)
        covariance = box(frame*reference)-mean*reference_mean
        structure.append(np.clip(covariance / np.maximum(np.sqrt(variance*reference_variance), 1e-5), -1, 1))
        if progress:
            progress('structure', done, n, '')
    structure = np.stack(structure)
    seeds = ((structure.min(axis=0) >= config.structure_min_correlation)
             & (np.median(structure, axis=0) >= config.structure_median_correlation)
             & (reference_variance >= config.structure_std_floor**2)
             & fringe.astype(bool))
    # Every sampled frame must support the seed, including an occasional tilt.
    # Strong seeds estimate global gain/bias only; no spatial transformation.
    gains, residuals = [], []
    exposure_valid = np.count_nonzero(seeds) >= config.min_component_pixels
    if exposure_valid:
        design = np.column_stack((reference[seeds], np.ones(np.count_nonzero(seeds))))
        for frame in stack:
            _cancel(cancelled)
            gain, bias = np.linalg.lstsq(design, frame[seeds], rcond=None)[0]
            gains.append(float(gain))
            if not math.isfinite(gain) or not math.isfinite(bias) or not .15 <= gain <= 4 or abs(bias) > .5:
                exposure_valid = False
                break
            residuals.append(np.abs((frame-bias)/gain-reference))
    raw_stable = np.max(stack, axis=0)-np.min(stack, axis=0) <= config.temporal_range_max
    exposure_stable = (np.max(residuals, axis=0) <= config.exposure_residual_max) if exposure_valid else np.zeros((h,w), bool)
    support = raw_stable | exposure_stable | seeds
    distance = cv2.distanceTransform((~seeds).astype(np.uint8), cv2.DIST_L2, 5)
    eligible = (support & (distance <= config.growth_pixels) & fringe.astype(bool)).astype(np.uint8)
    # Close only tiny gaps with independent temporal support. Do not fill a
    # solid region just because an approximate contour encloses it.
    kernel = np.ones((config.shape_close_pixels, config.shape_close_pixels), np.uint8)
    eligible = cv2.morphologyEx(eligible, cv2.MORPH_CLOSE, kernel)
    eligible &= (support & (distance <= config.growth_pixels) & fringe.astype(bool)).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(eligible, connectivity=8)
    border_ids = set(np.concatenate((labels[0], labels[-1], labels[:, 0], labels[:, -1])).tolist()) - {0}
    excluded = np.zeros_like(eligible, dtype=bool)
    components = []
    for label in sorted(border_ids):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area >= config.min_component_pixels and np.count_nonzero((labels == label) & seeds) >= min(8, config.min_component_pixels):
            excluded |= labels == label
            components.append(dict(pixels=area, bbox=[int(v) for v in stats[label, :4]]))
    fraction = float(excluded.mean())
    metrics = dict(median_motion_fraction=float(np.median(motion)),
                   moving_pairs_fraction=float(np.mean(motion >= config.min_motion_fraction)),
                   median_center_correlation=float(np.median(correlations)) if correlations else 1.0,
                   center_detail_fraction=center_detail, candidate_fraction=fraction,
                   edge_connected_components=components, structural_seed_pixels=int(np.count_nonzero(seeds)),
                   exposure_model_valid=bool(exposure_valid),
                   exposure_gain_range=[min(gains), max(gains)] if gains else None)
    blockers = []
    if metrics['moving_pairs_fraction'] < config.min_moving_pairs_fraction:
        blockers.append('low_motion_or_stationary_camera')
    if metrics['median_center_correlation'] >= config.max_center_correlation:
        blockers.append('stationary_or_scene_registered_structure')
    if center_detail < config.min_center_detail_fraction:
        blockers.append('insufficient_scene_detail_for_motion_evidence')
    if fraction > config.max_candidate_fraction:
        blockers.append('candidate_area_exceeds_limit')
    return excluded, metrics, blockers


def assess_temporal_occlusion(frames, *, source_root, batch_id, selection_hash,
                              config=None, cancelled=None, progress=None):
    """Return serializable candidates/guards; no source or artifact writes.

    progress(stage, done, total, path). Each group must represent one POST-BATCH
    camera/family/extent. Configuration defaults are engineering proposals.
    """
    config = config or TemporalMaskConfig()
    config.validate()
    _sha(selection_hash)
    if not isinstance(batch_id, str) or not batch_id.strip():
        raise ValueError('Explicit batch_id required')
    source = Path(source_root).resolve(strict=True)
    frames = list(frames)
    for frame in frames:
        _cancel(cancelled)
        if not Path(frame.path).resolve(strict=True).is_relative_to(source):
            raise ValueError('Frame outside declared source_root')
    sampled, distinct_count = select_temporal_samples(frames, config)
    blocks = plan_temporal_blocks(frames, block_seconds=config.block_seconds)
    if len(blocks) != 1 or blocks[0]['block_id'] != batch_id:
        raise ValueError('batch_id must name one canonical temporal block; never use a zone or whole dive')
    stack, records, dimensions = [], [], None
    for done, frame in enumerate(sampled, 1):
        _cancel(cancelled)
        gray, extent = _pixels(frame)
        if dimensions is not None and extent != dimensions:
            raise ValueError('Frame dimensions/dtype mismatch')
        dimensions = extent
        scale = min(1, config.analysis_long_edge / max(gray.shape))
        size = (round(gray.shape[1] * scale), round(gray.shape[0] * scale))
        stack.append(cv2.resize(gray, size, interpolation=cv2.INTER_AREA))
        record = asdict(frame)
        record['path'] = str(Path(frame.path).resolve())
        record['timestamp_utc'] = _utc(frame.timestamp_utc).isoformat()
        records.append(record)
        if progress:
            progress('decode', done, len(sampled), record['path'])
    _cancel(cancelled)
    excluded, metrics, blockers = _analyze(np.stack(stack), config, cancelled=cancelled, progress=progress)
    span = (_utc(records[-1]['timestamp_utc']) - _utc(records[0]['timestamp_utc'])).total_seconds()
    if len(sampled) < config.min_samples:
        blockers.append('insufficient_distinct_samples')
    if span < config.min_span_seconds:
        blockers.append('insufficient_time_span')
    metrics['sample_span_seconds'] = span
    if not excluded.any():
        blockers.append('no_supported_edge_occlusion')
    assessment = dict(version=VERSION, batch_id=batch_id, selection_hash=selection_hash,
                      membership_hash=blocks[0]['membership_hash'],
                      image_ids=[m['image_id'] for m in blocks[0]['members']],
                      source_root=str(source), camera=sampled[0].camera, family=sampled[0].family,
                      frame_extent=sampled[0].frame_extent, config=asdict(config),
                      supplied_frames=len(frames), distinct_available=distinct_count,
                      sampled_frames=records, width=dimensions[0], height=dimensions[1], dtype=dimensions[2],
                      analysis_width=excluded.shape[1], analysis_height=excluded.shape[0],
                      excluded_runs=_runs(excluded), metrics=metrics, blockers=blockers,
                      status='blocked' if blockers else 'candidate_review_required',
                      convention='white_includes_black_excludes',
                      limitation='Temporal persistence is not semantic proof of ROV hardware; review every proposed exclusion.')
    _cancel(cancelled)
    if progress:
        progress('complete', len(sampled), len(sampled), '')
    _cancel(cancelled)
    return dict(assessment, assessment_hash=digest(assessment))


def _validate(assessment):
    if not isinstance(assessment, dict) or assessment.get('version') != VERSION:
        raise ValueError('Unsupported temporal assessment')
    if assessment.get('assessment_hash') != digest({k: v for k, v in assessment.items() if k != 'assessment_hash'}):
        raise ValueError('Temporal assessment hash mismatch')
    TemporalMaskConfig(**assessment['config']).validate()


def candidate_mask(assessment):
    """Full-resolution uint8 preview array, white INCLUDE / black EXCLUDE.
    A blocked assessment is evidence only and cannot be approved or published.
    """
    _validate(assessment)
    h, w = assessment['analysis_height'], assessment['analysis_width']
    if type(h) is not int or type(w) is not int or min(h, w) <= 0 or h*w > 1024**2:
        raise ValueError('Invalid analysis dimensions')
    mask = np.full(h*w, 255, np.uint8)
    end = 0
    for start, length in assessment['excluded_runs']:
        if type(start) is not int or type(length) is not int or start < end or length <= 0 or start+length > h*w:
            raise ValueError('Invalid candidate runs')
        mask[start:start+length] = 0
        end = start+length
    width, height = assessment['width'], assessment['height']
    if type(width) is not int or type(height) is not int or min(width, height) <= 0 or width*height > MAX_PIXELS:
        raise ValueError('Invalid output dimensions')
    return cv2.resize(mask.reshape(h, w), (width, height), interpolation=cv2.INTER_NEAREST)


def _destination(root, assessment):
    root = Path(root).resolve()
    source = Path(assessment['source_root'])
    if root.is_relative_to(source) or source.is_relative_to(root):
        raise ValueError('Output must be disjoint from source_root')
    root.mkdir(parents=True, exist_ok=True)
    return root


def write_temporal_preview(assessment, *, artifact_dir):
    """Write evidence to a fresh directory. Preview PNG is not an approved mask."""
    mask = candidate_mask(assessment)
    root = _destination(artifact_dir, assessment)
    folder = Path(tempfile.mkdtemp(prefix=assessment['assessment_hash'][:12]+'-', dir=root))
    # Use first/middle/last sampled frames to avoid suggesting one frame proves
    # all exclusions. Check bytes again before overlaying.
    panels = []
    records = assessment['sampled_frames']
    for index in sorted({0, len(records)//2, len(records)-1}):
        frame = TemporalFrame(**records[index])
        gray, extent = _pixels(frame)
        if extent != (assessment['width'], assessment['height'], assessment['dtype']):
            raise ValueError('Preview frame extent changed')
        size = (assessment['analysis_width'], assessment['analysis_height'])
        scene = cv2.resize((gray*255).astype(np.uint8), size, interpolation=cv2.INTER_AREA)
        scene = cv2.cvtColor(scene, cv2.COLOR_GRAY2BGR)
        small = cv2.resize(mask, size, interpolation=cv2.INTER_NEAREST)
        overlay = scene.copy()
        overlay[small == 0] = (overlay[small == 0].astype(np.float32)*.5 + np.array([0, 0, 255])*.5).astype(np.uint8)
        panel = np.concatenate((scene, overlay), axis=1)
        panel = cv2.copyMakeBorder(panel, 45, 0, 0, 0, cv2.BORDER_CONSTANT, value=(255,255,255))
        cv2.putText(panel, f'Sample {index+1}: original | RED=candidate exclusion', (4, 18), cv2.FONT_HERSHEY_SIMPLEX, .42, (0,0,0), 1)
        cv2.putText(panel, 'PREVIEW ONLY: white mask includes; black excludes', (4, 36), cv2.FONT_HERSHEY_SIMPLEX, .42, (0,0,0), 1)
        panels.append(panel)
    for name, pixels in (('candidate.preview.png', mask), ('overlay.preview.png', np.concatenate(panels, axis=0))):
        ok, encoded = cv2.imencode('.png', pixels)
        if not ok:
            raise ValueError('Unable to encode preview')
        (folder/name).write_bytes(encoded.tobytes())
    write_json(folder/'assessment.json', assessment)
    return dict(assessment_hash=assessment['assessment_hash'], status=assessment['status'],
                mask_preview_path=str(folder/'candidate.preview.png'), overlay_path=str(folder/'overlay.preview.png'),
                assessment_path=str(folder/'assessment.json'))


def approve_temporal_mask(assessment, *, assessment_hash, confirmed_by):
    """Call only on explicit user acceptance of the exact candidate preview."""
    _validate(assessment)
    if assessment_hash != assessment['assessment_hash']:
        raise ValueError('Approval refers to a different assessment')
    if assessment['blockers'] or assessment['status'] != 'candidate_review_required':
        raise ValueError('Blocked temporal mask cannot be approved')
    if not isinstance(confirmed_by, str) or not confirmed_by.strip():
        raise ValueError('confirmed_by is required')
    record = dict(version=VERSION, assessment_hash=assessment_hash,
                  selection_hash=assessment['selection_hash'], batch_id=assessment['batch_id'],
                  decision='accept_candidate', confirmed_by=confirmed_by.strip(),
                  confirmed_at=datetime.now(timezone.utc).isoformat())
    return dict(record, approval_hash=digest(record))


def publish_temporal_mask(assessment, approval, *, output_dir, selection_hash):
    """Publish a new immutable master mask after review; never copy to images.
    The controller validates its live batch/selection and copies only this master
    beside batch images as '<original image filename>.mask.png'.
    """
    mask = candidate_mask(assessment)
    if assessment['blockers'] or assessment['status'] != 'candidate_review_required':
        raise ValueError('Blocked temporal mask cannot be published')
    if not isinstance(approval, dict) or approval.get('approval_hash') != digest({k:v for k,v in approval.items() if k!='approval_hash'}):
        raise ValueError('Explicit valid approval required')
    for key, value in (('version', VERSION), ('assessment_hash', assessment['assessment_hash']),
                       ('selection_hash', selection_hash), ('batch_id', assessment['batch_id']),
                       ('decision', 'accept_candidate')):
        if approval.get(key) != value:
            raise ValueError(f'Stale temporal approval: {key}')
    if selection_hash != assessment['selection_hash'] or not approval.get('confirmed_by', '').strip():
        raise ValueError('Explicit current selection approval required')
    _utc(approval.get('confirmed_at'))
    # Recheck every sampled hash before publication. Other batch inputs are the
    # controller's inventory gate responsibility.
    for row in assessment['sampled_frames']:
        if _read(Path(row['path']))[1] != row['sha256']:
            raise ValueError('Sample changed since temporal review')
    root = _destination(output_dir, assessment)
    folder = Path(tempfile.mkdtemp(prefix=assessment['assessment_hash'][:12]+'-', dir=root))
    ok, encoded = cv2.imencode('.png', mask)
    if not ok:
        raise ValueError('Unable to encode approved mask')
    content = encoded.tobytes()
    # A short digest is a filesystem-safe name; full identity remains in record.
    name = 'camera-' + digest([assessment['camera'], assessment['family'], assessment['frame_extent']])[:16] + '.mask.png'
    path = folder/name
    path.write_bytes(content)
    record = dict(version=VERSION, assessment_hash=assessment['assessment_hash'], approval=approval,
                  batch_id=assessment['batch_id'], camera=assessment['camera'], family=assessment['family'],
                  selection_hash=assessment['selection_hash'], membership_hash=assessment['membership_hash'],
                  image_ids=assessment['image_ids'], parameters=assessment['config'],
                  frame_extent=assessment['frame_extent'], output_path=str(path), output_sha256=hashlib.sha256(content).hexdigest(),
                  width=assessment['width'], height=assessment['height'], dtype='uint8',
                  convention='white_includes_black_excludes', source_samples=assessment['sampled_frames'])
    write_json(folder/'provenance.json', record)
    return record
