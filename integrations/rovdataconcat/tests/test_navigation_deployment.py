from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import pytest

import navigation
from navigation import source_window, source_plan, copy_inputs, manifested_log_files, log_window_selection
from processors.common import best_fix_per_second, determine_utm_zone
from processors.dive_summaries import process_data, process_dive_folder


def source_fixture(tmp_path):
    source = tmp_path / "source"
    root = source / "cruise_data"
    report = root / "proc/processed/dive_reports/H2101"
    report.mkdir(parents=True)
    (report / "H2101-stats.csv").write_text(
        "## NA171\tdive\tinwatertime\tondecktime\ttotaltime(hours)\n"
        "NA171\tH2101\t2025-05-23T22:00:00Z\t2025-05-24T02:00:00Z\t4\n")
    (report / "H2101-summary.txt").write_text("Objective: Fixture\n")
    for folder in ("raw/nav/navest", "raw/datalog", "raw/sealog/sealog-herc/H2101"):
        (root / folder).mkdir(parents=True)
    (root / "raw/nav/navest/20250523_2200.DAT").write_text("test fixture\n")
    (root / "raw/datalog/20250523_2200.SDYN").write_text("test fixture\n")
    return source, report


def test_csv_named_tsv_and_redirected_outputs(tmp_path):
    source, report = source_fixture(tmp_path)
    output = tmp_path / "project/proc/nav"
    before = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
    process_data(source / "cruise_data", reports_dir=report.parent,
                 output_dir=output, dive="H2101")
    assert (output / "all_dive_summaries.csv").is_file()
    assert all(p.read_bytes() == content for p, content in before.items())
    assert not (source / "cruise_data/RUMI_processed").exists()


def test_source_window_reads_only_report_without_sensor_inventory(tmp_path, monkeypatch):
    source, report = source_fixture(tmp_path)
    project = tmp_path / 'project'
    original_open = Path.open

    def report_only(path, *args, **kwargs):
        assert path.parent == report, f'Unexpected content read: {path}'
        return original_open(path, *args, **kwargs)

    def no_inventory(*args, **kwargs):
        pytest.fail('Window lookup must not enumerate source directories')

    monkeypatch.setattr(Path, 'open', report_only)
    monkeypatch.setattr(Path, 'iterdir', no_inventory)
    monkeypatch.setattr(Path, 'rglob', no_inventory)
    monkeypatch.setattr(navigation, 'log_window_selection', no_inventory)
    window = source_window(str(source), str(project), 'NA171', 'H2101')
    assert window['launch_utc'] == '2025-05-23T22:00:00+00:00'
    assert window['recovery_utc'] == '2025-05-24T02:00:00+00:00'
    assert window['delivery_root'] == str(source / 'cruise_data')
    assert window['raw_root'] == str(project / 'raw/navigation/NA171')
    assert 'files' not in window and 'copy_bytes' not in window
    assert not project.exists()


def test_source_window_reuses_conflicting_stats_guard(tmp_path):
    source, report = source_fixture(tmp_path)
    (report / 'H2101-stats.tsv').write_text('conflicting')
    with pytest.raises(ValueError, match='Conflicting'):
        source_window(source, tmp_path / 'project', 'NA171', 'H2101')


def test_full_plan_reuses_window_and_still_requires_sensor_directories(tmp_path, monkeypatch):
    source, _ = source_fixture(tmp_path)
    window = source_window(source, tmp_path / 'project', 'NA171', 'H2101')
    called = []

    def shared_window(*args):
        called.append(args)
        return window

    monkeypatch.setattr(navigation, 'source_window', shared_window)
    plan = source_plan(source, tmp_path / 'project', 'NA171', 'H2101')
    assert len(called) == 1
    assert all(plan[key] == value for key, value in window.items())
    window['navest_root'] = str(tmp_path / 'missing')
    with pytest.raises(FileNotFoundError):
        source_plan(source, tmp_path / 'project', 'NA171', 'H2101')


def test_coverage_cache_reuses_complete_range_but_invalidates_changed_file(tmp_path, monkeypatch):
    path = tmp_path / 'renamed.DAT'
    path.write_text('OCT 2025/05/21 00:00:00.0 Hercules\n')
    launch = datetime(2025, 5, 23, 22, tzinfo=timezone.utc)
    recovery = datetime(2025, 5, 24, 2, tzinfo=timezone.utc)
    cache = {}
    assert log_window_selection(path, launch, recovery, coverage_cache=cache) == 'outside_record_window'
    assert cache[str(path.resolve())]['complete'] is True
    original_open = Path.open
    opens = []

    def counted_open(path, *args, **kwargs):
        opens.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', counted_open)
    assert log_window_selection(path, launch, recovery, coverage_cache=cache) == 'outside_record_window'
    assert log_window_selection(path, launch.replace(day=25), recovery.replace(day=26), coverage_cache=cache) == 'outside_record_window'
    assert opens == []
    path.write_text('OCT 2025/05/23 22:15:00.00 Hercules\n')
    opens.clear()
    assert log_window_selection(path, launch, recovery, coverage_cache=cache) == 'record_time_overlaps_window'
    assert opens == [path]
    assert cache[str(path.resolve())]['complete'] is False


def test_coverage_range_overlap_is_not_evidence_of_actual_record(tmp_path):
    path = tmp_path / 'gap.DAT'
    path.write_text('OCT 2025/05/23 20:00:00.0 Hercules\n'
                    'OCT 2025/05/24 04:00:00.0 Hercules\n')
    cache = {}
    launch = datetime(2025, 5, 25, 22, tzinfo=timezone.utc)
    recovery = datetime(2025, 5, 26, 2, tzinfo=timezone.utc)
    assert log_window_selection(path, launch, recovery, coverage_cache=cache) == 'outside_record_window'
    assert log_window_selection(path, launch.replace(day=23), recovery.replace(day=24), coverage_cache=cache) == 'outside_record_window'


def test_partial_coverage_cache_cannot_exclude_later_records(tmp_path):
    path = tmp_path / 'multiday.DAT'
    path.write_text('OCT 2025/05/23 22:15:00.0 Hercules\n'
                    'OCT 2025/05/25 22:15:00.0 Hercules\n')
    cache = {}
    launch = datetime(2025, 5, 23, 22, tzinfo=timezone.utc)
    recovery = datetime(2025, 5, 24, 2, tzinfo=timezone.utc)
    assert log_window_selection(path, launch, recovery, coverage_cache=cache) == 'record_time_overlaps_window'
    assert log_window_selection(path, launch.replace(day=25), recovery.replace(day=26), coverage_cache=cache) == 'record_time_overlaps_window'


def test_unknown_cached_coverage_remains_included_in_other_window(tmp_path):
    path = tmp_path / 'legacy.SDYN'
    path.write_text('$GPGGA,undated legacy record\n')
    cache = {}
    launch = datetime(2025, 5, 23, 22, tzinfo=timezone.utc)
    recovery = datetime(2025, 5, 24, 2, tzinfo=timezone.utc)
    assert log_window_selection(path, launch, recovery, coverage_cache=cache) == 'unknown_coverage_included'
    assert log_window_selection(path, launch.replace(day=25), recovery.replace(day=26), coverage_cache=cache) == 'unknown_coverage_included'


def test_source_change_during_scan_does_not_publish_cache(tmp_path):
    path = tmp_path / 'changing.DAT'
    path.write_text('OCT 2025/05/21 00:00:00.0 Hercules\n')
    cache = {}

    def modify(*args):
        path.write_text('OCT 2025/05/23 22:15:00.00 Hercules\n')

    with pytest.raises(ValueError, match='Source changed'):
        log_window_selection(path, datetime(2025, 5, 23, 22, tzinfo=timezone.utc),
                             datetime(2025, 5, 24, 2, tzinfo=timezone.utc),
                             coverage_cache=cache, progress=modify)
    assert not cache


def test_cache_policy_version_change_forces_rescan(tmp_path):
    path = tmp_path / 'stale.DAT'
    path.write_text('OCT 2025/05/23 22:15:00.0 Hercules\n')
    cache = {}
    launch = datetime(2025, 5, 23, 22, tzinfo=timezone.utc)
    recovery = datetime(2025, 5, 24, 2, tzinfo=timezone.utc)
    log_window_selection(path, launch, recovery, coverage_cache=cache)
    cache[str(path.resolve())]['identity']['version'] = -1
    cache[str(path.resolve())]['decision'] = 'outside_record_window'
    assert log_window_selection(path, launch, recovery, coverage_cache=cache) == 'record_time_overlaps_window'


def test_cancel_during_scan_does_not_publish_partial_cache(tmp_path):
    path = tmp_path / 'large.DAT'
    path.write_text('OCT 2025/05/21 00:00:00.0 Hercules\n' * 9000)
    cache, events = {}, []
    launch = datetime(2025, 5, 23, 22, tzinfo=timezone.utc)
    recovery = datetime(2025, 5, 24, 2, tzinfo=timezone.utc)
    with pytest.raises(InterruptedError, match='cancelled'):
        log_window_selection(path, launch, recovery, coverage_cache=cache,
                             progress=lambda *event: events.append(event),
                             cancelled=lambda: len(events) >= 2)
    assert '4096 lines' in events[-1][2]
    assert not cache


def test_full_plan_progress_and_cancellation(tmp_path):
    source, _ = source_fixture(tmp_path)
    events = []
    plan = source_plan(source, tmp_path / 'project', 'NA171', 'H2101',
                       progress=lambda *event: events.append(event))
    assert len(plan['log_selection']) == 2
    assert events[-1][:2] == (2, 2)
    with pytest.raises(InterruptedError):
        source_plan(source, tmp_path / 'project', 'NA171', 'H2101', cancelled=lambda: True)
    assert not (tmp_path / 'project').exists()


def test_conflicting_stats_are_not_silently_selected(tmp_path):
    _, report = source_fixture(tmp_path)
    (report / "H2101-stats.tsv").write_text("different")
    with pytest.raises(ValueError, match="Conflicting"):
        process_dive_folder(report, "H2101")


def test_copy_hashes_and_refuses_changed_existing_copy(tmp_path):
    source, _ = source_fixture(tmp_path)
    plan = source_plan(source, tmp_path / "project", "NA171", "H2101")
    assert not (tmp_path / "project").exists()
    copy_inputs(plan, 0)
    assert all(len(item["sha256"]) == 64 for item in plan["files"])
    target = Path(plan["files"][0]["copy"])
    target.write_text("changed")
    with pytest.raises(FileExistsError):
        copy_inputs(plan, 0)
    assert target.read_text() == "changed"


def test_source_and_project_cannot_overlap(tmp_path):
    source, _ = source_fixture(tmp_path)
    with pytest.raises(ValueError, match="separate"):
        source_plan(source, source / "project", "NA171", "H2101")


def test_duplicate_dataframe_index_does_not_corrupt_best_fix():
    frame = pd.DataFrame({"Timestamp": ["2025-01-01T00:00:00.1Z",
                                         "2025-01-01T00:00:00.2Z",
                                         "2025-01-01T00:00:01.1Z"],
                          "Accuracy": [10, 1, 2]}, index=[0, 0, 1])
    result, _, count = best_fix_per_second(frame, "Accuracy")
    assert count == 2
    assert result["Accuracy"].tolist() == [1, 2]


@pytest.mark.parametrize("lon,lat", [(float("nan"), 1), (0, 85), (181, 0)])
def test_utm_invalid_coordinates_rejected(lon, lat):
    with pytest.raises(ValueError):
        determine_utm_zone(lon, lat)


def test_antimeridian_uses_valid_zone():
    assert determine_utm_zone(180, 0) == (60, "north")


@pytest.mark.parametrize('suffix,payload', [
    ('.DAT', 'OCT 2025/05/23 22:15:00.000 Hercules 0 0 0\n'),
    ('.SDYN', 'SDYN\t2025-05-23T22:15:00Z\tSONARDYNE\t$GPGGA,fixture\n'),
])
def test_renamed_log_selected_by_record_time(tmp_path, suffix, payload):
    source, _ = source_fixture(tmp_path)
    folder = source / ('cruise_data/raw/nav/navest' if suffix == '.DAT' else 'cruise_data/raw/datalog')
    renamed = folder / ('19990101_0000' + suffix)
    renamed.write_text(payload)
    plan = source_plan(source, tmp_path / 'project', 'NA171', 'H2101')
    assert str(renamed) in [entry['source'] for entry in plan['files']]
    assert next(entry for entry in plan['log_selection'] if entry['source'] == str(renamed))['decision'] == 'record_time_overlaps_window'


def test_multiday_out_of_order_log_scanned_beyond_first_record(tmp_path):
    path = tmp_path / '20200101_0000.DAT'
    path.write_text('OCT 2025/05/25 00:00:00.0 Hercules\n'
                    'OCT 2025/05/22 00:00:00.0 Hercules\n'
                    'OCT 2025/05/23 22:15:00.0 Hercules\n')
    launch = datetime(2025, 5, 23, 22, tzinfo=timezone.utc)
    recovery = datetime(2025, 5, 24, 2, tzinfo=timezone.utc)
    assert log_window_selection(path, launch, recovery) == 'record_time_overlaps_window'
    path.write_text('OCT 2025/05/22 00:00:00.0 Hercules\n')
    assert log_window_selection(path, launch, recovery) == 'outside_record_window'
    path.write_text('$GPGGA,undated legacy record\n')
    assert log_window_selection(path, launch, recovery) == 'unknown_coverage_included'


def test_sdyn_receipt_margin_retains_boundary_acquisition(tmp_path):
    path = tmp_path / 'wrong-name.SDYN'
    path.write_text('SDYN 2025-05-24T02:00:00.5Z SONARDYNE $GPGGA,fixture\n')
    assert log_window_selection(path, datetime(2025, 5, 23, 22, tzinfo=timezone.utc),
                                datetime(2025, 5, 24, 2, tzinfo=timezone.utc)) == 'record_time_overlaps_window'


def test_manifest_list_excludes_stale_copied_logs_and_checks_hashes(tmp_path):
    source, _ = source_fixture(tmp_path)
    plan = source_plan(source, tmp_path / 'project', 'NA171', 'H2101')
    copy_inputs(plan, 0)
    stale = Path(plan['raw_root']) / 'raw/datalog/stale.SDYN'
    stale.write_text('not in current manifest')
    selected = manifested_log_files(plan, verify_hashes=True)
    assert stale not in selected['.sdyn']
    assert len(selected['.sdyn']) == len(selected['.dat']) == 1
    selected['.sdyn'][0].write_text('tampered')
    with pytest.raises(ValueError, match='hash differs'):
        manifested_log_files(plan, verify_hashes=True)


def test_auxiliary_report_dat_is_copied_but_not_parsed_as_navest(tmp_path):
    source, report = source_fixture(tmp_path)
    auxiliary = report / 'H2101.SVP.ascent.tracklink.dat'
    auxiliary.write_text('profile data, not a NavEst log')
    plan = source_plan(source, tmp_path / 'project', 'NA171', 'H2101')
    copy_inputs(plan, 0)
    entry = next(item for item in plan['files'] if item['source'] == str(auxiliary))
    assert Path(entry['copy']).read_bytes() == auxiliary.read_bytes()
    assert Path(entry['copy']) not in manifested_log_files(plan, verify_hashes=True)['.dat']


@pytest.mark.parametrize('damage', ['duplicate', 'outside', 'wrong_sensor_folder'])
def test_invalid_manifest_refused_before_copy_writes(tmp_path, damage):
    source, _ = source_fixture(tmp_path)
    project = tmp_path / 'project'
    plan = source_plan(source, project, 'NA171', 'H2101')
    if damage == 'duplicate':
        plan['files'].append(dict(plan['files'][0]))
    elif damage == 'outside':
        plan['files'][0]['copy'] = str(tmp_path / 'escape.DAT')
    else:
        plan['files'][0]['copy'] = str(Path(plan['raw_root']) / 'raw/datalog/wrong.DAT')
    with pytest.raises(ValueError):
        copy_inputs(plan, 0)
    assert not project.exists()


def test_entrypoint_passes_exact_manifest_lists_to_both_parsers(tmp_path, monkeypatch):
    source, _ = source_fixture(tmp_path)
    plan = source_plan(source, tmp_path / 'project', 'NA171', 'H2101')
    calls = {}

    def fake_extract(name):
        def call(root, output_dir=None, **kwargs):
            calls[name] = kwargs
            (output_dir / 'H2101').mkdir(exist_ok=True)
        return call

    for name in ('dive_summaries', 'process_dat', 'usbl_sdyn', 'sensors_sealog'):
        monkeypatch.setattr(getattr(navigation, name), 'process_data', fake_extract(name))
    monkeypatch.setattr(navigation, 'stage_status', lambda *args: 'ok')
    monkeypatch.setattr(navigation.kalman_concat, 'process_data', lambda *args: None)

    def fake_filter(raw, output):
        (output / 'NA171_H2101_final_datatable.csv').write_text('fixture,not,a,real,run\n')

    monkeypatch.setattr(navigation.kalman_filter, 'process_data', fake_filter)
    navigation.run_navigation(plan, reserve_bytes=0)
    selected = manifested_log_files(plan)
    assert calls['process_dat']['files'] == selected['.dat']
    assert calls['usbl_sdyn']['files'] == selected['.sdyn']
