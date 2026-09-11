"""Offline temporal engineering fixtures, not semantic/field ground truth."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from modules import temporal_occlusion as temporal


def write(path, pixels):
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(path.suffix, pixels)
    assert ok
    path.write_bytes(encoded.tobytes())
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture_frames(tmp_path, *, count=24, kind='hardware'):
    source = tmp_path/'source'
    rng = np.random.default_rng(712)
    base = rng.integers(40, 170, (128, 192), dtype=np.uint8)
    yy, xx = np.indices(base.shape)
    hardware = np.where((xx//3+yy//3)%2, 210, 30).astype(np.uint8)
    rows = []
    for i in range(count):
        image = rng.integers(40, 170, base.shape, dtype=np.uint8)
        if kind == 'static':
            image = base.copy()
            image[60, 80] = i  # Distinct hashes without substantive scene motion.
        elif kind == 'exposure':
            image = (base.astype(np.int16)+i).astype(np.uint8)
        elif kind == 'water':
            image = np.full_like(base, 70+i)
        if kind in ('hardware', 'interior', 'moving_hardware', 'solid'):
            image[:, :20] = hardware[:, :20]
        if kind == 'solid':
            image[20:108, :15] = 120
        if kind == 'interior':
            image[45:75, 65:95] = hardware[45:75, 65:95]
        if kind == 'moving_hardware' and i == count-1:
            image[:, :20] = 120
        path = source/f'frame{i:03}.png'
        sha = write(path, image)
        stamp = datetime(2025,1,1,tzinfo=timezone.utc)+timedelta(seconds=i*10)
        rows.append(temporal.TemporalFrame(path, sha, 'lower', 'legacy_lower', stamp.isoformat(), 'sensor-full-orientation1', 192,128))
    return source, rows


def assess(source, frames, **overrides):
    config = replace(temporal.TemporalMaskConfig(), sample_count=24, min_samples=24, **overrides)
    block = temporal.plan_temporal_blocks(frames, block_seconds=config.block_seconds)[0]
    return temporal.assess_temporal_occlusion(frames, source_root=source, batch_id=block['block_id'],
                                              selection_hash='a'*64, config=config)


def test_moving_scene_with_stable_edge_hardware_is_candidate(tmp_path):
    source, frames = fixture_frames(tmp_path)
    result = assess(source, frames)
    assert result['status'] == 'candidate_review_required', result['blockers']
    mask = temporal.candidate_mask(result)
    assert (mask[:, :16] == 0).mean() > .8
    assert np.all(mask[:, 35:] == 255)
    assert set(np.unique(mask)) == {0, 255}
    assert result['metrics']['moving_pairs_fraction'] == 1
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize('kind', ['static', 'exposure', 'water'])
def test_stationary_scene_and_exposure_change_cannot_be_approved(tmp_path, kind):
    source, frames = fixture_frames(tmp_path, kind=kind)
    result = assess(source, frames)
    assert 'low_motion_or_stationary_camera' in result['blockers']
    with pytest.raises(ValueError, match='Blocked'):
        temporal.approve_temporal_mask(result, assessment_hash=result['assessment_hash'], confirmed_by='tester')


def test_interior_static_feature_never_excluded(tmp_path):
    source, frames = fixture_frames(tmp_path, kind='interior')
    result = assess(source, frames)
    mask = temporal.candidate_mask(result)
    assert np.all(mask[35:95, 40:152] == 255)
    assert (mask[:, :16] == 0).any()


def test_one_tilting_head_sample_disqualifies_changed_pixels(tmp_path):
    source, frames = fixture_frames(tmp_path, kind='moving_hardware')
    result = assess(source, frames)
    assert not np.any(temporal.candidate_mask(result)[:, :20] == 0)
    assert 'no_supported_edge_occlusion' in result['blockers']


def test_stable_solid_hardware_requires_nearby_structural_support(tmp_path):
    source, frames = fixture_frames(tmp_path, kind='solid')
    result = assess(source, frames)
    mask = temporal.candidate_mask(result)
    assert np.all(mask[40:90, :8] == 0)
    no_growth = assess(source, frames, growth_pixels=0)
    assert np.all(temporal.candidate_mask(no_growth)[40:90, :8] == 255)


def test_lighting_changes_do_not_remove_fixed_hardware_evidence(tmp_path):
    source, frames = fixture_frames(tmp_path)
    for i, frame in enumerate(frames):
        pixels = cv2.imread(str(frame.path), cv2.IMREAD_UNCHANGED).astype(np.float32)
        gain = .4 + .5*i/(len(frames)-1)
        altered = (pixels*gain+10).astype(np.uint8)
        frames[i] = replace(frame, sha256=write(Path(frame.path), altered))
    result = assess(source, frames)
    assert result['status'] == 'candidate_review_required'
    assert (temporal.candidate_mask(result)[:, :16] == 0).mean() > .8
    assert result['metrics']['exposure_model_valid']


def test_boundary_depth_is_enforced(tmp_path):
    source, frames = fixture_frames(tmp_path)
    result = assess(source, frames, fringe_fraction=.05)
    mask = temporal.candidate_mask(result)
    assert np.all(mask[8:-8, 10:] == 255)


def test_deterministic_sampling_and_overlap_membership(tmp_path):
    source, frames = fixture_frames(tmp_path, count=40)
    a = temporal.plan_temporal_blocks(frames)[0]
    b = temporal.plan_temporal_blocks(list(reversed(frames)))[0]
    assert a == b
    cfg = temporal.TemporalMaskConfig(sample_count=24)
    left, total = temporal.select_temporal_samples(frames, cfg)
    right, _ = temporal.select_temporal_samples(list(reversed(frames)), cfg)
    assert left == right and len(left) == 24 and total == 40
    assert left[0] == frames[0] and left[-1] == frames[-1]
    duplicate_path = source/'zone_overlap.png'
    duplicate_path.write_bytes(Path(frames[0].path).read_bytes())
    duplicate = replace(frames[0], path=duplicate_path)
    c = temporal.plan_temporal_blocks(frames+[duplicate])[0]
    assert c['membership_hash'] == a['membership_hash']
    assert temporal.canonical_image_id(duplicate) == temporal.canonical_image_id(frames[0])


def test_blocks_split_time_and_camera_and_extent(tmp_path):
    _, frames = fixture_frames(tmp_path, count=4)
    other = replace(frames[0], timestamp_utc='2025-01-01T00:16:00Z', sha256='b'*64)
    camera = replace(frames[1], camera='tilting_head')
    extent = replace(frames[2], frame_extent='crop1')
    assert len(temporal.plan_temporal_blocks(frames+[other,camera,extent])) == 4


def test_conflicting_timestamp_for_same_identity_fails(tmp_path):
    _, frames = fixture_frames(tmp_path, count=4)
    with pytest.raises(ValueError, match='conflicting timestamps'):
        temporal.plan_temporal_blocks(frames+[replace(frames[0], timestamp_utc='2025-01-01T01:00:00Z')])


@pytest.mark.parametrize('field,value', [('camera','other'), ('family','other'), ('frame_extent','crop'), ('width',190)])
def test_mixed_camera_or_frame_extent_fails(tmp_path, field, value):
    _, frames = fixture_frames(tmp_path, count=4)
    frames[-1] = replace(frames[-1], **{field:value})
    with pytest.raises(ValueError, match='Mixed'):
        temporal.select_temporal_samples(frames, temporal.TemporalMaskConfig())


@pytest.mark.parametrize('timestamp', ['', '2025-01-01T00:00:00', 'bad'])
def test_missing_or_naive_timestamp_rejected(tmp_path, timestamp):
    _, frames = fixture_frames(tmp_path, count=4)
    with pytest.raises(ValueError, match='timestamp'):
        temporal.plan_temporal_blocks([replace(frames[0], timestamp_utc=timestamp)])


def test_registered_frames_rejected(tmp_path):
    _, frames = fixture_frames(tmp_path, count=4)
    with pytest.raises(ValueError, match='Registered'):
        temporal.plan_temporal_blocks([replace(frames[0], registered=True)])


def test_actual_dimensions_and_content_verified(tmp_path):
    source, frames = fixture_frames(tmp_path)
    frames = [replace(f, width=190) for f in frames]
    with pytest.raises(ValueError, match='inventoried dimensions'):
        assess(source, frames)
    frames = [replace(f, width=192) for f in frames]
    Path(frames[0].path).write_bytes(b'changed')
    with pytest.raises(ValueError, match='content changed'):
        assess(source, frames)


def test_entire_dive_or_arbitrary_zone_id_rejected(tmp_path):
    source, frames = fixture_frames(tmp_path)
    with pytest.raises(ValueError, match='canonical temporal block'):
        temporal.assess_temporal_occlusion(frames, source_root=source, batch_id='zone_3', selection_hash='a'*64)


def test_insufficient_sample_and_time_guards(tmp_path):
    source, frames = fixture_frames(tmp_path, count=4)
    result = assess(source, frames)
    assert 'insufficient_distinct_samples' in result['blockers']
    assert 'insufficient_time_span' in result['blockers']


def test_no_source_writes_and_preview_is_not_approval(tmp_path):
    source, frames = fixture_frames(tmp_path)
    before = {p.name:p.read_bytes() for p in source.iterdir()}
    result = assess(source, frames)
    preview = temporal.write_temporal_preview(result, artifact_dir=tmp_path/'evidence')
    assert Path(preview['overlay_path']).is_file()
    assert Path(preview['mask_preview_path']).name == 'candidate.preview.png'
    assert not any('.mask.' in p.name for p in Path(preview['overlay_path']).parent.iterdir())
    with pytest.raises(ValueError, match='approval'):
        temporal.publish_temporal_mask(result, None, output_dir=tmp_path/'proc', selection_hash='a'*64)
    with pytest.raises(ValueError, match='disjoint'):
        temporal.write_temporal_preview(result, artifact_dir=source/'previews')
    assert {p.name:p.read_bytes() for p in source.iterdir()} == before


def test_explicit_approval_publishes_binary_mask_and_provenance(tmp_path):
    source, frames = fixture_frames(tmp_path)
    result = assess(source, frames)
    approval = temporal.approve_temporal_mask(result, assessment_hash=result['assessment_hash'], confirmed_by='test owner')
    published = temporal.publish_temporal_mask(result, approval, output_dir=tmp_path/'proc', selection_hash='a'*64)
    output = Path(published['output_path'])
    assert output.name.endswith('.mask.png')
    assert hashlib.sha256(output.read_bytes()).hexdigest() == published['output_sha256']
    assert np.array_equal(cv2.imread(str(output), cv2.IMREAD_UNCHANGED), temporal.candidate_mask(result))
    assert json.loads((output.parent/'provenance.json').read_text()) == published
    with pytest.raises(ValueError, match='Stale'):
        temporal.publish_temporal_mask(result, approval, output_dir=tmp_path/'proc', selection_hash='b'*64)
    Path(frames[0].path).write_bytes(b'changed')
    with pytest.raises(ValueError, match='changed'):
        temporal.publish_temporal_mask(result, approval, output_dir=tmp_path/'proc', selection_hash='a'*64)


def test_tamper_and_wrong_review_rejected(tmp_path):
    source, frames = fixture_frames(tmp_path)
    result = assess(source, frames)
    with pytest.raises(ValueError, match='different assessment'):
        temporal.approve_temporal_mask(result, assessment_hash='b'*64, confirmed_by='test')
    changed = dict(result, excluded_runs=[])
    with pytest.raises(ValueError, match='hash mismatch'):
        temporal.candidate_mask(changed)


@pytest.mark.parametrize('field,value', [('sample_count',True), ('sample_count',0), ('fringe_fraction',.4),
 ('max_candidate_fraction',.8), ('detail_threshold',float('nan')), ('block_seconds',86400)])
def test_config_limits(field, value):
    with pytest.raises(ValueError):
        replace(temporal.TemporalMaskConfig(), **{field:value}).validate()


def test_parameter_schema_includes_growth_and_odd_windows_without_gui_clamping():
    schema = {r['key']:r for r in temporal.parameter_schema()}
    defaults = temporal.TemporalMaskConfig()
    assert defaults.sample_count == schema['sample_count']['default'] == 96
    assert defaults.min_samples == schema['min_samples']['default'] == 24
    assert defaults.block_seconds == schema['block_seconds']['default'] == 900
    defaults.validate()
    assert set(schema) == set(temporal.asdict(temporal.TemporalMaskConfig()))
    assert schema['structure_window']['max'] == 31
    assert schema['structure_window']['step'] == 2
    assert schema['growth_pixels']['min'] == 0
    assert schema['growth_pixels']['default'] == 12
    for spec in schema.values():
        assert spec['min'] <= spec['default'] <= spec['max']
    with pytest.raises(ValueError, match='step'):
        replace(temporal.TemporalMaskConfig(), structure_window=10).validate()


def test_cancellation_and_progress(tmp_path):
    source, frames = fixture_frames(tmp_path)
    block = temporal.plan_temporal_blocks(frames)[0]
    calls = []
    with pytest.raises(InterruptedError):
        temporal.assess_temporal_occlusion(frames, source_root=source, batch_id=block['block_id'], selection_hash='a'*64,
          cancelled=lambda: len(calls) >= 2, progress=lambda *args: calls.append(args))
    assert [call[1] for call in calls] == [1,2]
