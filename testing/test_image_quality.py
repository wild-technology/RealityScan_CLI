"""Synthetic engineering fixtures; these are not field validation."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from modules.image_quality import ScreeningThresholds, assess_image


def write_image(path, pixels):
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode('.png', pixels)
    assert ok
    path.write_bytes(encoded.tobytes())
    return path


def blue():
    return np.full((512, 768, 3), (150, 90, 30), dtype=np.uint8)


def useful_frame(weak=False):
    frame = blue()
    if weak:
        # Only 1.7% of the frame, crossing primary grid boundaries. No strong
        # bounding rectangle: detail oscillates around the original intensity.
        y, x = np.mgrid[:80, :80]
        signal = np.rint(5 * np.sin(x / 3) * np.cos(y / 4)).astype(np.int16)
        frame[220:300, 344:424] = np.clip(
            frame[220:300, 344:424].astype(np.int16) + signal[..., None], 0, 255)
    else:
        # Bottom fifth, rounded to whole rows; 80% uniform blue MUST KEEP.
        y, x = np.mgrid[:103, :768]
        signal = ((x // 12 + y // 12) % 2) * 80 - 40
        frame[-103:] = np.clip(frame[-103:].astype(np.int16) + signal[..., None], 0, 255)
    return frame


@pytest.mark.parametrize('color', [(150, 90, 30), (90, 90, 90), (30, 90, 150)])
def test_uniform_frame_is_nonsemantic_candidate(tmp_path, color):
    result = assess_image(write_image(tmp_path / 'image.png', np.full((512, 768, 3), color, np.uint8)))
    assert result['candidate']
    assert result['reason'] == 'low_texture_candidate'
    assert result['exclusion_requires_confirmation']
    assert result['assessment_complete']
    assert result['metrics']['tile_counts']['textured_patch'] == 0
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize('weak', [False, True])
def test_any_coherent_patch_keeps_whole_frame(tmp_path, weak):
    result = assess_image(write_image(tmp_path / 'image.png', useful_frame(weak)))
    assert result['decision'] == 'keep'
    assert result['reason'] == 'meaningful_textured_patch'
    assert not result['candidate']


@pytest.mark.parametrize('rotation,scale', [(0, .5), (0, 1), (0, 2), (1, 1), (2, 1), (3, 1)])
def test_unmasked_water_with_only_thin_edge_texture_requires_review(tmp_path, rotation, scale):
    frame = blue()
    y, x = np.mgrid[:32, :768]
    # A textured vehicle-like fringe on otherwise uniform water. Geometry is
    # deliberately also compatible with an edge scene: no semantic assertion.
    signal = ((x // 6 + y // 6) % 2) * 140 - 70
    frame[-32:] = np.clip(frame[-32:].astype(np.int16) + signal[..., None], 0, 255)
    frame = np.rot90(frame, rotation).copy()
    frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
    result = assess_image(write_image(tmp_path / 'edge.png', frame))
    assert result['metrics']['tile_counts']['textured_patch'] > 0
    assert result['metrics']['interior_textured_tiles'] == 0
    assert result['decision'] == 'review_required'
    assert result['reason'] == 'edge_only_detail_uncertain'
    assert not result['candidate'] and result['exclusion_requires_confirmation']
    assert result['mask_sha256'] is None


@pytest.mark.parametrize('rotation', range(4))
def test_twenty_percent_textured_scene_at_each_edge_still_keeps(tmp_path, rotation):
    result = assess_image(write_image(tmp_path / 'scene.png', np.rot90(useful_frame(), rotation).copy()))
    assert result['decision'] == 'keep'
    assert result['metrics']['interior_textured_tiles'] > 0


@pytest.mark.parametrize('corner', range(4))
def test_twenty_percent_corner_scene_still_keeps(tmp_path, corner):
    frame = blue()
    h, w = 205, 384  # 20% of the image, against two edges.
    y, x = np.mgrid[:h, :w]
    signal = ((x // 12 + y // 12) % 2) * 80 - 40
    top = 0 if corner < 2 else 512 - h
    left = 0 if corner % 2 == 0 else 768 - w
    patch = frame[top:top+h, left:left+w].astype(np.int16)
    frame[top:top+h, left:left+w] = np.clip(patch + signal[..., None], 0, 255)
    assert assess_image(write_image(tmp_path / 'corner.png', frame))['decision'] == 'keep'


@pytest.mark.parametrize('kind', ['uniform', 'twenty_percent', 'weak'])
def test_decision_stable_across_fixture_scales(tmp_path, kind):
    frame = blue() if kind == 'uniform' else useful_frame(kind == 'weak')
    decisions = []
    for scale in (0.5, 1, 2):
        pixels = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
        result = assess_image(write_image(tmp_path / f'{scale}.png', pixels))
        decisions.append(result['decision'])
        assert result['metrics']['analysis_width'] == 768
    assert decisions == ['candidate' if kind == 'uniform' else 'keep'] * 3


def test_relative_corners_do_not_certify_uniform_noise(tmp_path):
    rng = np.random.default_rng(19)
    frame = np.clip(blue().astype(np.int16) + rng.integers(-1, 2, (512, 768, 1)), 0, 255).astype(np.uint8)
    result = assess_image(write_image(tmp_path / 'noise.png', frame))
    assert max(t.get('raw_corners', 0) for t in result['tiles']) > 3
    assert result['decision'] != 'keep'
    assert result['metrics']['tile_counts']['textured_patch'] == 0


def test_sparse_particulate_is_conservatively_kept_or_uncertain(tmp_path):
    frame = blue()
    for x, y in [(120, 140), (270, 180), (360, 260), (520, 320), (630, 420)]:
        cv2.circle(frame, (x, y), 2, (230, 230, 230), -1)
    result = assess_image(write_image(tmp_path / 'scatter.png', frame))
    assert result['decision'] in ('keep', 'review_required')
    assert not result['candidate']


def test_isolated_pixel_prompts_uncertainty_instead_of_candidate(tmp_path):
    frame = blue()
    frame[260, 360] = 230
    result = assess_image(write_image(tmp_path / 'point.png', frame))
    assert result['decision'] == 'review_required'
    assert result['reason'] == 'sparse_or_weak_detail_uncertain'


def test_fragmented_mask_cannot_certify_coverage_after_erosion(tmp_path):
    mask = np.full((512, 768), 255, np.uint8)
    mask[::20, :] = 0
    mask[:, ::20] = 0
    result = assess_image(write_image(tmp_path / 'image.png', blue()),
                          mask_path=write_image(tmp_path / 'mask.png', mask))
    assert result['metrics']['valid_fraction'] > 0.8
    assert result['metrics']['analysis_coverage'] < 0.9
    assert result['decision'] == 'review_required'


def test_masked_texture_and_mask_boundary_are_not_evidence(tmp_path):
    path = write_image(tmp_path / 'image.png', useful_frame())
    mask = np.full((512, 768), 255, np.uint8)
    mask[-103:] = 0
    mask_path = write_image(tmp_path / 'mask.png', mask)
    assert assess_image(path)['decision'] == 'keep'
    result = assess_image(path, mask_path=mask_path)
    assert result['decision'] == 'candidate'
    assert result['metrics']['tile_counts']['textured_patch'] == 0


@pytest.mark.parametrize('valid_pixels', [0, 20])
def test_insufficient_mask_support_requires_review(tmp_path, valid_pixels):
    mask = np.zeros((512, 768), np.uint8)
    mask[:valid_pixels] = 255
    result = assess_image(write_image(tmp_path / 'image.png', blue()),
                          mask_path=write_image(tmp_path / 'mask.png', mask))
    assert result['decision'] == 'review_required'
    assert result['reason'] == 'insufficient_unmasked_support'


@pytest.mark.parametrize('fraction', [0.14, 0.22])
def test_textured_small_valid_mask_region_cannot_certify_keep(tmp_path, fraction):
    image = write_image(tmp_path / 'image.png', useful_frame())
    mask = np.zeros((512, 768), np.uint8)
    mask[-round(512 * fraction):] = 255
    result = assess_image(image, mask_path=write_image(tmp_path / 'mask.png', mask))
    assert result['metrics']['tile_counts']['textured_patch'] > 0
    assert result['metrics']['valid_fraction'] < ScreeningThresholds().min_valid_fraction
    assert result['decision'] == 'review_required' and not result['candidate']
    assert result['reason'] == 'insufficient_unmasked_support'
    assert assess_image(image)['decision'] == 'keep'  # Smooth water remains valid support.


def test_inadequate_analysis_coverage_precedes_textured_tile(tmp_path):
    mask = np.zeros((512, 768), np.uint8)
    mask[:, ::2] = 255  # Erosion removes fragmented support.
    mask[-103:] = 255  # A meaningful textured region survives.
    result = assess_image(write_image(tmp_path / 'image.png', useful_frame()),
                          mask_path=write_image(tmp_path / 'mask.png', mask))
    assert result['metrics']['valid_fraction'] > ScreeningThresholds().min_valid_fraction
    assert result['metrics']['analysis_coverage'] < ScreeningThresholds().min_analysis_coverage
    assert result['metrics']['tile_counts']['textured_patch'] > 0
    assert result['decision'] == 'review_required' and not result['candidate']


def test_assessor_version_change_invalidates_identical_input_fingerprint(tmp_path, monkeypatch):
    from modules import image_quality
    image = write_image(tmp_path / 'image.png', useful_frame())
    assert image_quality.ALGORITHM_VERSION == 'local-detail-3'
    current = assess_image(image)
    monkeypatch.setattr(image_quality, 'ALGORITHM_VERSION', 'local-detail-2')
    old = assess_image(image)
    assert old['assessment_fingerprint'] != current['assessment_fingerprint']


@pytest.mark.parametrize('bad_mask', ['corrupt', 'size', 'color', 'nonbinary', 'missing'])
def test_bad_masks_never_produce_candidate(tmp_path, bad_mask):
    path = write_image(tmp_path / 'image.png', blue())
    mask_path = tmp_path / 'mask.png'
    if bad_mask == 'corrupt':
        mask_path.write_bytes(b'not an image')
    elif bad_mask != 'missing':
        shape = (40, 40) if bad_mask == 'size' else (512, 768, 3) if bad_mask == 'color' else (512, 768)
        write_image(mask_path, np.full(shape, 127 if bad_mask == 'nonbinary' else 255, np.uint8))
    result = assess_image(path, mask_path=mask_path)
    assert result['decision'] == 'review_required'
    assert not result['assessment_complete']
    assert result['errors']


@pytest.mark.parametrize('content', [b'', b'corrupt'])
def test_corrupt_image_never_produces_candidate(tmp_path, content):
    path = tmp_path / 'image.png'
    path.write_bytes(content)
    result = assess_image(path)
    assert result['decision'] == 'review_required'
    assert not result['assessment_complete']
    assert result['errors']
    assert path.read_bytes() == content


def test_full_range_16bit_and_grayscale_supported(tmp_path):
    frame = useful_frame(True)
    a = assess_image(write_image(tmp_path / '8.png', frame))
    b = assess_image(write_image(tmp_path / '16.png', frame.astype(np.uint16) * 257))
    assert a['decision'] == b['decision'] == 'keep'
    assert assess_image(write_image(tmp_path / 'gray.png', np.full((512, 768), 90, np.uint8)))['candidate']


def test_fingerprint_tracks_content_masks_thresholds_and_not_paths(tmp_path):
    path = write_image(tmp_path / 'a.png', blue())
    copy = tmp_path / 'b.png'
    copy.write_bytes(path.read_bytes())
    a = assess_image(path)
    assert a['assessment_fingerprint'] == assess_image(copy)['assessment_fingerprint']
    assert a['image_sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    changed = assess_image(path, thresholds=replace(ScreeningThresholds(), contrast_floor=0.007))
    assert changed['assessment_fingerprint'] != a['assessment_fingerprint']
    masked = assess_image(path, mask_path=write_image(tmp_path / 'mask.png', np.ones((512, 768), np.uint8)))
    assert masked['assessment_fingerprint'] != a['assessment_fingerprint']
    write_image(path, useful_frame())
    assert assess_image(path)['assessment_fingerprint'] != a['assessment_fingerprint']


def test_clahe_is_diagnostic_only(tmp_path):
    path = write_image(tmp_path / 'weak.png', useful_frame(True))
    before = path.read_bytes()
    plain = assess_image(path)
    diagnostic = assess_image(path, thresholds=replace(ScreeningThresholds(), diagnostic_clahe=True))
    assert diagnostic['decision'] == plain['decision']
    assert diagnostic['tiles'] == plain['tiles']
    assert 'diagnostic_clahe_corners' in diagnostic['metrics']
    assert path.read_bytes() == before


def test_artifacts_are_optional_fresh_and_leave_source_unchanged(tmp_path):
    path = write_image(tmp_path / 'source' / 'image.png', useful_frame())
    before = path.read_bytes()
    root = tmp_path / 'project' / 'proc' / 'tmp' / 'image_quality'
    plain = assess_image(path)
    assert plain['thumbnail_path'] is None
    first = assess_image(path, artifact_dir=root)
    second = assess_image(path, artifact_dir=root)
    assert not first['errors']
    assert first['assessment_fingerprint'] == second['assessment_fingerprint']
    assert first['report_path'] != second['report_path']
    assert json.loads(Path(first['report_path']).read_text()) == first
    assert len(first['tile_grid']) == 8
    assert len(first['tiles']) == 113
    for key in ('report_path', 'thumbnail_path', 'heatmap_path'):
        assert Path(first[key]).is_relative_to(root)
        assert Path(first[key]).is_file()
    assert path.read_bytes() == before
    assert list(path.parent.iterdir()) == [path]


def test_source_folder_artifact_destination_refused_before_writes(tmp_path):
    path = write_image(tmp_path / 'source' / 'image.png', blue())
    root = path.parent / 'diagnostics'
    result = assess_image(path, artifact_dir=root)
    assert not root.exists()
    assert result['errors']
    assert result['thumbnail_path'] is None


@pytest.mark.parametrize('field,value', [('contrast_floor', float('nan')), ('gradient_floor', 0),
                                      ('grid_size', True), ('analysis_long_edge', 20),
                                      ('corner_quality', 1.1), ('diagnostic_clahe', 1),
                                      ('edge_band_fraction', .5), ('edge_band_fraction', float('nan')),
                                      ('contrast_floor', '0.006')])
def test_invalid_thresholds_fail_before_reading(tmp_path, field, value):
    with pytest.raises(ValueError):
        assess_image(tmp_path / 'absent.png', thresholds=replace(ScreeningThresholds(), **{field: value}))
