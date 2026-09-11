"""Offline spatial-review acceptance; candidates never change selection."""
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from modules.spatial_review import SpatialThresholds, assess_spatial, points_from_matches
from modules.source_inventory import SourceItem
from modules.navigation_quality import match_images, POSE_COLUMNS


def point(name, x, y=0.0, *, seconds=0, camera='cinema', excluded=False):
    return {'path': name, 'x': 500000.0 + x, 'y': 1800000.0 + y,
            'camera': camera, 'time': (pd.Timestamp('2025-01-01T00:00:00Z')
                                     + pd.Timedelta(seconds=seconds)).isoformat(),
            'excluded': excluded}


def site(prefix, x=0, y=0, count=30):
    return [point(f'{prefix}-{i:05}.jpg', x + (i % 6), y + (i // 6), seconds=i) for i in range(count)]


def test_isolated_few_accidental_frames_are_candidates_only():
    points = site('survey') + [point(f'burst-{i}.jpg', 1000 + i, seconds=60 + i) for i in range(3)]
    report = assess_spatial(points, epsg=32655)
    assert report['candidate_count'] == 3
    assert all(p['outlier'] for p in report['points'] if p['path'].startswith('burst'))
    assert report['kept_count'] == len(points)
    assert not report['automatic_exclusion']
    assert all(not p['excluded'] for p in report['points'])


def test_large_separate_legitimate_sites_are_retained():
    report = assess_spatial(site('first') + site('second', x=5000), epsg=32655)
    assert report['candidate_count'] == 0
    assert len(report['components']) == 2


def test_rare_useful_bridge_between_sites_is_preserved():
    points = site('left', x=-500) + site('right', x=500) + [point('bridge.jpg', 0, 2)]
    report = assess_spatial(points, epsg=32655)
    bridge = next(p for p in report['points'] if p['path'] == 'bridge.jpg')
    assert not bridge['outlier']
    assert 'bridge' in bridge['reason']


def test_sparse_camera_is_not_isolated_from_other_camera_evidence():
    points = site('dense') + [point('rare.jpg', 10, camera='zeuss')]
    report = assess_spatial(points, epsg=32655)
    assert report['candidate_count'] == 0


def test_long_sparse_observation_is_not_a_short_accidental_burst():
    points = site('survey') + [point('remote-a', 1000, seconds=0), point('remote-b', 1001, seconds=200)]
    assert assess_spatial(points, epsg=32655)['candidate_count'] == 0


def test_small_dataset_without_supported_survey_is_not_rejected():
    points = [point('a', 0), point('b', 1000)]
    assert assess_spatial(points, epsg=32655)['candidate_count'] == 0


def test_supported_coincident_frames_do_not_hide_an_isolated_burst():
    base = point('base', 0)
    points = [{**base, 'path': f'same-{i}.jpg'} for i in range(30)]
    points += [point('isolated', 1000)]
    report = assess_spatial(points, epsg=32655)
    assert report['candidate_count'] == 1


def test_excluded_points_stay_visible_and_support_kept_culled_density_toggle():
    points = site('survey')
    points[0]['excluded'] = True
    report = assess_spatial(points, epsg=32655)
    assert len(report['points']) == 30
    assert report['kept_count'] == 29 and report['excluded_count'] == 1
    assert all(p['neighbors'] == 30 and p['kept_neighbors'] == 29 for p in report['points'])


def test_hash_is_order_independent_and_binds_selection_coordinates_thresholds_and_crs():
    points = site('survey')
    before = assess_spatial(points, epsg=32655)['assessment_hash']
    assert assess_spatial(points[::-1], epsg=32655)['assessment_hash'] == before
    points[0]['excluded'] = True
    assert assess_spatial(points, epsg=32655)['assessment_hash'] != before
    points[0]['excluded'] = False
    points[0]['x'] += 0.0001
    assert assess_spatial(points, epsg=32655)['assessment_hash'] != before
    points[0]['x'] -= 0.0001
    assert assess_spatial(points, epsg=32755)['assessment_hash'] != before
    thresholds = replace(SpatialThresholds(), isolation_distance_m=201)
    assert assess_spatial(points, epsg=32655, thresholds=thresholds)['assessment_hash'] != before


@pytest.mark.parametrize('key,value', [('x', float('nan')), ('x', float('inf')), ('y', None),
                                     ('x', True), ('time', 'NaT'), ('time', '2025-01-01'),
                                     ('excluded', 'false'), ('camera', '')])
def test_invalid_pose_time_or_selection_is_rejected(key, value):
    p = point('invalid', 0)
    p[key] = value
    with pytest.raises(ValueError):
        assess_spatial([p], epsg=32655)


@pytest.mark.parametrize('epsg', [4326, 32600, 32761, '32655', None, True])
def test_explicit_valid_utm_crs_required(epsg):
    with pytest.raises(ValueError, match='UTM EPSG'):
        assess_spatial([], epsg=epsg)


@pytest.mark.parametrize('key,value', [('epsg', 32755), ('utm_zone', '54N')])
def test_mixed_zone_points_cannot_be_reviewed_in_one_plane(key, value):
    p = point('wrong-zone', 0)
    p[key] = value
    with pytest.raises(ValueError, match='CRS/zone'):
        assess_spatial([p], epsg=32655)


def test_float64_coordinates_keep_submetre_offsets_at_far_origin():
    points = [point('first', 1e9), point('second', 1e9 + 0.125)]
    report = assess_spatial(points, epsg=32655)
    assert report['points'][1]['x'] - report['points'][0]['x'] == 0.125


def test_empty_points_and_explicit_track_have_deterministic_json():
    import json
    report = assess_spatial([], epsg=32655, track=[[500000.0, 1800000.0]])
    assert report['points'] == [] and report['candidate_count'] == 0
    json.dumps(report, allow_nan=False)
    with pytest.raises(ValueError, match='Track'):
        assess_spatial([], epsg=32655, track=[[float('nan'), 0]])


@pytest.mark.parametrize('settings', [{'neighbor_radius_m': -1}, {'neighbor_links': 100000},
                                     {'max_candidate_images': 65}, {'min_site_images': 2},
                                     {'bridge_angle_degrees': 180}, {'isolation_distance_m': 10}])
def test_invalid_thresholds_refused(settings):
    with pytest.raises(ValueError):
        assess_spatial([], epsg=32655, thresholds=settings)


def test_adapter_preserves_excluded_matches_and_rejects_zone_mismatch():
    frame = pd.DataFrame({'Timestamp': pd.to_datetime(['2025-01-01T00:00:00Z'], utc=True),
                          'utm_zone': ['55N']})
    for column in POSE_COLUMNS:
        frame[column] = 1.0
    items = [SourceItem('a.jpg', 'a.jpg', 'image', 1, 1, camera='cinema',
                        timestamp_utc='2025-01-01T00:00:00Z', included=False)]
    matches = match_images(items, frame, include_excluded=True)
    points = points_from_matches(items, frame, matches, epsg=32655)
    assert points[0]['excluded'] is True
    with pytest.raises(ValueError, match='zone'):
        points_from_matches(items, frame, matches, epsg=32755)


def test_one_hundred_thousand_points_without_pairwise_matrix():
    # Coincident dense data is particularly dangerous for unbounded DBSCAN
    # radius graphs. Bounded k-neighbor storage remains linear here.
    base = point('base', 0)
    points = [{**base, 'path': f'frame-{i:06}.jpg'} for i in range(100000)]
    report = assess_spatial(points, epsg=32655)
    assert len(report['points']) == 100000
    assert report['candidate_count'] == 0
    assert report['points'][0]['neighbors'] == 100000
