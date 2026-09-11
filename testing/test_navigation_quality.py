import pandas as pd
import pytest

from modules.navigation_quality import POSE_COLUMNS, match_images, load_navigation, assess_navigation
from modules.source_inventory import SourceItem


def frame():
    result = pd.DataFrame({"Timestamp": pd.to_datetime([
        "2025-05-24T00:00:00Z", "2025-05-24T00:00:04Z"], utc=True).as_unit("us")})
    for column in POSE_COLUMNS:
        result[column] = 1.0
    return result


def item(timestamp):
    return SourceItem("photo.jpg", "photo.jpg", "image", 1, 1,
                      camera="zeuss", timestamp_utc=timestamp)


def test_match_respects_datetime_units_and_exact_boundary():
    result = match_images([item("2025-05-24T00:00:02+00:00")], frame(), 2)
    assert result["matched_count"] == 1
    assert result["matched"][0]["delta_s"] == 2
    assert result["matched"][0]["nav_row"] == 0


def test_no_extrapolation_even_within_match_tolerance():
    result = match_images([item("2025-05-23T23:59:59+00:00")], frame(), 2)
    assert result["unmatched_count"] == 1


def test_nonfinite_pose_is_unmatched():
    data = frame()
    data.loc[0, "kalman_depth"] = float("nan")
    result = match_images([item("2025-05-24T00:00:00+00:00")], data)
    assert result["unmatched_count"] == 1


def test_matching_can_cancel_without_returning_a_partial_selection():
    checks = iter([False, True])
    photos = [item("2025-05-24T00:00:00Z"), item("2025-05-24T00:00:04Z")]
    with pytest.raises(InterruptedError, match="cancelled"):
        match_images(photos, frame(), cancelled=lambda: next(checks))


def test_matching_progress_and_nonnumeric_pose_keep_row_local_failures():
    data = frame()
    data["kalman_depth"] = ["invalid", "2.5"]
    updates = []
    result = match_images([item("2025-05-24T00:00:00Z"), item("2025-05-24T00:00:04Z")], data,
                          progress=lambda *args: updates.append(args))
    assert result["matched_count"] == result["unmatched_count"] == 1
    assert result["matched"][0]["nav_row"] == 1
    assert updates[-1][:2] == (2, 2)


def test_wrong_navigation_identity_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="filename"):
        load_navigation(tmp_path / "NA171_H2100_final_datatable.csv", "NA171", "H2101")


@pytest.mark.parametrize('timestamp', ['', 'NaT', 'not a date', '2025-02-30T00:00:00Z', '2025-05-24T00:00:00'])
def test_invalid_image_timestamps_report_unmatched(timestamp):
    result = match_images([item(timestamp)], frame())
    assert result['matched_count'] == 0 and result['unmatched_count'] == 1


@pytest.mark.parametrize('problem', ['empty', 'unordered', 'duplicate', 'nat', 'naive'])
def test_invalid_navigation_frames_rejected(problem):
    data = frame()
    if problem == 'empty':
        data = data.iloc[:0]
    elif problem == 'unordered':
        data = data.iloc[::-1]
    elif problem == 'duplicate':
        data.loc[1, 'Timestamp'] = data.loc[0, 'Timestamp']
    elif problem == 'nat':
        data.loc[0, 'Timestamp'] = pd.NaT
    else:
        data['Timestamp'] = data['Timestamp'].dt.tz_localize(None)
    with pytest.raises(ValueError, match='Navigation'):
        match_images([item('2025-05-24T00:00:00Z')], data)


def write_nav(tmp_path, suffix='.csv', separator=',', nonfinite=False):
    from pyproj import Transformer
    data = frame().iloc[:1].copy()
    data['Timestamp'] = ['2025-05-24T00:00:00Z']
    data['utm_zone'] = '55N'
    data['kalman_lat'], data['kalman_long'] = 17.0, 145.0
    x, y = Transformer.from_crs(4326, 32655, always_xy=True).transform(145.0, 17.0)
    data['kalman_x'], data['kalman_y'] = x, y
    data['kalman_depth'] = float('nan') if nonfinite else -100.0
    path = tmp_path / ('NA999_H9999_final_datatable' + suffix)
    data.to_csv(path, sep=separator, index=False)
    return path


@pytest.mark.parametrize('suffix,separator', [('.tsv', ','), ('.csv', '\t'), ('.csv', ';')])
def test_delimiter_is_read_from_content_not_suffix(tmp_path, suffix, separator):
    path = write_nav(tmp_path, suffix, separator)
    data = load_navigation(path, 'NA999', 'H9999')
    assert len(data) == 1 and data.attrs['source_sha256']


def test_single_row_and_invalid_pose_reports_are_strict_json(tmp_path):
    import json
    path = write_nav(tmp_path, nonfinite=True)
    result = assess_navigation(path, 'NA999', 'H9999')
    assert not result['structurally_valid']
    assert result['depth_min_m'] is None
    assert result['max_gap_s'] == 0.0
    json.dumps(result, allow_nan=False)


def test_navigation_change_during_csv_read_invalidates_result(tmp_path, monkeypatch):
    import modules.navigation_quality as quality
    path = write_nav(tmp_path)
    original = quality.pd.read_csv

    def changing_read(*args, **kwargs):
        result = original(*args, **kwargs)
        path.write_bytes(path.read_bytes() + b'\n')
        return result

    monkeypatch.setattr(quality.pd, 'read_csv', changing_read)
    with pytest.raises(ValueError, match='changed while loading'):
        load_navigation(path, 'NA999', 'H9999')


@pytest.mark.parametrize('timestamp,offset,row', [
    ('2025-05-23T23:59:58Z', 2, 0),
    ('2025-05-24T00:00:06Z', -2, 1),
    ('2025-05-23T23:59:59.750Z', 0.25, 0),
    ('2025-05-24T00:00:04.250Z', -0.25, 1),
    ('2025-05-23T00:00:00Z', 86400, 0),
    ('2025-05-25T00:00:04Z', -86400, 1),
])
def test_clock_offset_applied_once_without_changing_inventory(tmp_path, timestamp, offset, row):
    from copy import deepcopy
    from modules.source_inventory import SourceInventory, approval_token
    photo = item(timestamp)
    photo.sha256 = 'a' * 64
    inventory = SourceInventory([photo], source_root=tmp_path, fingerprint='snapshot')
    before = deepcopy(inventory)
    token = approval_token(inventory)
    data = frame()
    nav_before = data.copy(deep=True)
    first = match_images(inventory, data, 0, clock_offset_seconds=offset)
    assert first['matched_count'] == 1
    record = first['matched'][0]
    assert record['nav_row'] == row and record['delta_s'] == 0
    assert record['timestamp_utc'] == timestamp
    assert pd.Timestamp(record['match_timestamp_utc']) == data.iloc[row]['Timestamp']
    assert first['clock_offset_seconds'] == offset
    assert match_images(inventory, data, 0, clock_offset_seconds=offset) == first
    assert inventory == before and approval_token(inventory) == token
    pd.testing.assert_frame_equal(data, nav_before)


@pytest.mark.parametrize('offset', [float('nan'), float('inf'), -float('inf'),
                                  86400.001, -86400.001, True, None, '2', [], 1j, 10**400])
def test_invalid_clock_offset_rejected_even_without_images(offset):
    with pytest.raises(ValueError, match='Clock offset'):
        match_images([], frame(), clock_offset_seconds=offset)


def test_default_offset_matches_explicit_zero():
    images = [item('2025-05-24T00:00:02Z')]
    assert match_images(images, frame()) == match_images(images, frame(), clock_offset_seconds=0)


def test_offset_cannot_extrapolate_or_bypass_tolerance():
    images = [item('2025-05-24T00:00:00Z')]
    outside = match_images(images, frame(), clock_offset_seconds=-1)
    assert 'extrapolation refused' in outside['unmatched'][0]['exception']
    gap = match_images(images, frame(), 1, clock_offset_seconds=2)
    assert '2.000 s away' in gap['unmatched'][0]['exception']


@pytest.mark.parametrize('timestamp', ['', 'NaT', '2025-05-24T00:00:00',
                                       '2262-04-11T23:47:16.854775807Z'])
def test_offset_does_not_invent_invalid_or_overflowing_timestamp(timestamp):
    result = match_images([item(timestamp)], frame(), clock_offset_seconds=1)
    assert result['matched_count'] == 0 and result['unmatched_count'] == 1
