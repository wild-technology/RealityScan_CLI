"""
Tests for the C-20260827-05 review fixes:

1. Stage return codes propagate (no silent failure-to-'ok' conversion).
2. Resume skips only FRESH outputs (stale output -> loud rerun).
3. UTM zone derived once and reused across USBL/DVL/offset.
4. SDYN midnight-rollover heuristic only fires on a genuine wrap.
5. Dive-summary TSV field-count and chronology validation.
6. VFR lat/long and OCT heading range gates (rejects counted).
7. Case-insensitive glob dedupe on Windows.

Run from the repository root:  python -m pytest tests/ -v
"""

import os
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import main_kalman
from main_kalman import (process_module, module_output_path, module_input_path,
                         module_input_paths, newest_existing_input)
from processors.common import proj_string_for_zone_label
from processors.usbl_sdyn import parse_sdyn_file, process_all_sdyn_files
from processors.process_dat import parse_dat_file_both, process_all_dat_files_both
from processors.dive_summaries import process_dive_folder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def gpgga(time_s, lat="0540.350", ns="N", lon="13356.905", ew="E",
          acc="14.5", depth="-1020.5", beacon="0001"):
    body = (f"GPGGA,{time_s},{lat},{ns},{lon},{ew},1,08,{acc},{depth},"
            f"M,0.0,M,0.0,{beacon}")
    checksum = 0
    for byte in body.encode("ascii"):
        checksum ^= byte
    return f"${body}*{checksum:02X}"


def oct_line(ts="2024/11/05 23:13:02.123", heading=228.42, pitch=-6.5, roll=-1.05):
    skip3 = "1.0 2.0 3.0"
    return (f"OCT {ts} Hercules {skip3} {heading} {pitch} {roll} "
            f"{skip3} 4.0 5.0 6.0 7.0 8.0 9.0")


def vfr_line(ts="2024/11/05 23:13:02.50", vehicle="0", fix="SOLN_DEADRECK",
             lon=133.948, lat=5.672):
    return f"VFR {ts} 123 {vehicle} {fix} {lon} {lat}"


def make_processed_dir(tmp_path, exp="NA167", dive="H2075"):
    processed = tmp_path / exp / "RUMI_processed" / dive
    processed.mkdir(parents=True)
    return processed


def make_stub(monkeypatch, name, fn):
    """Install a stub processors.<name> module so process_module runs it."""
    mod = types.ModuleType(f"processors.{name}")
    mod.process_data = fn
    monkeypatch.setitem(sys.modules, f"processors.{name}", mod)
    return mod


def write_filtered_datatable(processed_dir, exp="NA167", dive="H2075",
                             usbl_lon=133.995, dvl_lon=None, n=12):
    """Synthetic kalman_filter input (filtered_datatable) with n rows."""
    ts = pd.date_range("2024-11-05T12:00:00Z", periods=n, freq="1s")
    df = pd.DataFrame({
        "Timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "Vehicle": "Hercules",
        "Herc_Depth_1": -100.0,
        "Heading": np.linspace(10, 20, n),
        "Pitch": 0.5,
        "Roll": -0.5,
        "Lat_USBL": 5.0,
        "Long_USBL": usbl_lon,
        "Accuracy_USBL": 5.0,
    })
    if dvl_lon is not None:
        df["Lat_DVL"] = 5.0
        df["Long_DVL"] = dvl_lon
    path = processed_dir / f"{exp}_{dive}_filtered_datatable.csv"
    df.to_csv(path, index=False)
    return path


# ---------------------------------------------------------------------------
# FIX 1 -- return-code propagation / no silent failure conversion
# ---------------------------------------------------------------------------

class TestRcPropagation:
    def test_truthy_return_code_marks_stage_failed(self, monkeypatch, tmp_path):
        make_stub(monkeypatch, "stub_rc_fail", lambda raw, proc: 1)
        status = process_module("stub_rc_fail", tmp_path, tmp_path, auto_yes=True)
        assert status == "failed"

    def test_raising_stage_marks_failed(self, monkeypatch, tmp_path):
        def boom(raw, proc):
            raise RuntimeError("stage exploded")
        make_stub(monkeypatch, "stub_raise", boom)
        status = process_module("stub_raise", tmp_path, tmp_path, auto_yes=True)
        assert status == "failed"

    def test_zero_return_code_is_ok(self, monkeypatch, tmp_path):
        make_stub(monkeypatch, "stub_ok", lambda raw, proc: 0)
        status = process_module("stub_ok", tmp_path, tmp_path, auto_yes=True)
        assert status == "ok"

    def test_main_exits_nonzero_on_stage_failure(self, monkeypatch, tmp_path):
        make_processed_dir(tmp_path)
        make_stub(monkeypatch, "stub_rc_fail", lambda raw, proc: 1)
        monkeypatch.setattr(main_kalman, "KALMAN_MODULES", ["stub_rc_fail"])
        monkeypatch.setattr(sys, "argv", [
            "main_kalman.py", "--base", str(tmp_path),
            "--expedition", "NA167", "--dive", "H2075", "--yes",
        ])
        with pytest.raises(SystemExit) as excinfo:
            main_kalman.main()
        assert excinfo.value.code == 1

    def test_main_exits_zero_when_all_stages_pass(self, monkeypatch, tmp_path, capsys):
        make_processed_dir(tmp_path)
        make_stub(monkeypatch, "stub_ok", lambda raw, proc: 0)
        monkeypatch.setattr(main_kalman, "KALMAN_MODULES", ["stub_ok"])
        monkeypatch.setattr(sys, "argv", [
            "main_kalman.py", "--base", str(tmp_path),
            "--expedition", "NA167", "--dive", "H2075", "--yes",
        ])
        main_kalman.main()  # must not raise SystemExit
        assert "stub_ok" in capsys.readouterr().out

    def test_kalman_filter_reraises_on_missing_input(self, tmp_path):
        from processors import kalman_filter
        processed = make_processed_dir(tmp_path)
        with pytest.raises(FileNotFoundError):
            kalman_filter.process_data(processed, processed)

    def test_kalman_assess_raises_on_missing_input(self, tmp_path):
        from processors import kalman_assess
        processed = make_processed_dir(tmp_path)
        with pytest.raises(FileNotFoundError):
            kalman_assess.process_data(processed, processed)


# ---------------------------------------------------------------------------
# FIX 2 -- resume freshness (stale output triggers rerun)
# ---------------------------------------------------------------------------

class TestResumeFreshness:
    def _setup(self, tmp_path, out_older_than_input):
        processed = make_processed_dir(tmp_path)
        inp = module_input_path("kalman_filter", processed)
        out = module_output_path("kalman_filter", processed)
        inp.write_text("input\n")
        out.write_text("output\n")
        now = 1_700_000_000
        if out_older_than_input:
            os.utime(inp, (now, now))
            os.utime(out, (now - 3600, now - 3600))
        else:
            os.utime(inp, (now - 3600, now - 3600))
            os.utime(out, (now, now))
        return processed

    def test_stale_output_reruns_in_yes_mode(self, monkeypatch, tmp_path):
        processed = self._setup(tmp_path, out_older_than_input=True)
        ran = []
        make_stub(monkeypatch, "kalman_filter",
                  lambda raw, proc: ran.append(1) and None)
        status = process_module("kalman_filter", processed, processed, auto_yes=True)
        assert ran, "stale stage must rerun, not skip"
        assert status == "ok"

    def test_stale_output_reruns_in_interactive_mode(self, monkeypatch, tmp_path):
        processed = self._setup(tmp_path, out_older_than_input=True)
        ran = []
        make_stub(monkeypatch, "kalman_filter",
                  lambda raw, proc: ran.append(1) and None)

        def no_input(prompt=""):
            raise AssertionError("stale rerun must not prompt")
        monkeypatch.setattr("builtins.input", no_input)
        status = process_module("kalman_filter", processed, processed, auto_yes=False)
        assert ran and status == "ok"

    def test_fresh_output_still_skipped_in_yes_mode(self, monkeypatch, tmp_path):
        processed = self._setup(tmp_path, out_older_than_input=False)
        ran = []
        make_stub(monkeypatch, "kalman_filter",
                  lambda raw, proc: ran.append(1) and None)
        status = process_module("kalman_filter", processed, processed, auto_yes=True)
        assert not ran
        assert status == "skipped"

    def test_module_input_paths(self):
        processed = Path("Z:/NA167/RUMI_processed/H2075")
        assert module_input_path("kalman_filter", processed).name == \
            "NA167_H2075_filtered_datatable.csv"
        assert module_input_path("kalman_assess", processed).name == \
            "NA167_H2075_kalman_filtered_data.csv"
        assert module_input_path("kalman_offset", processed).name == \
            "NA167_H2075_final_datatable.csv"
        # kalman_concat declared "input": None until Aug 2026, which broke the
        # staleness chain at its root -- its output is kalman_filter's declared
        # input, so an mtime that never advanced made every downstream stage
        # look fresh too, and stage 2 became a one-shot per dive. It now
        # declares the four stage-1 files it actually reads.
        concat_inputs = module_input_paths("kalman_concat", processed)
        assert [p.name for p in concat_inputs] == [
            "NA167_H2075_USBL_Hercules.csv",
            "NA167_H2075_pitch_roll_heading_octans.csv",
            "NA167_H2075_dvl_lat_long.csv",
            "NA167_H2075_sealog_sensors_merged.csv",
        ]
        assert module_input_path("kalman_concat", processed) == concat_inputs[0]
        assert module_input_path("unknown_module", processed) is None
        assert module_input_paths("unknown_module", processed) == []

    def test_concat_goes_stale_when_a_stage1_input_is_regenerated(self, tmp_path):
        # The regression: regenerate ONE stage-1 file and kalman_concat must
        # stop counting as fresh, so a corrected nav rerun cannot be skipped.
        processed = make_processed_dir(tmp_path)
        out = module_output_path("kalman_concat", processed)
        out.write_text("x\n")
        base = out.stat().st_mtime
        inputs = module_input_paths("kalman_concat", processed)
        for p in inputs:
            p.write_text("x\n")
            os.utime(p, (base - 100, base - 100))
        assert newest_existing_input("kalman_concat", processed)[1] < base

        os.utime(inputs[2], (base + 100, base + 100))
        newest = newest_existing_input("kalman_concat", processed)
        assert newest[0] == inputs[2]
        assert newest[1] > base


# ---------------------------------------------------------------------------
# FIX 3 -- single UTM zone shared across USBL / DVL / offset
# ---------------------------------------------------------------------------

class TestSharedUtmZone:
    def test_boundary_straddle_uses_one_zone_for_both_sources(self):
        # ADAPTED in the fe2242c x 169ca4a merge: fe2242c's derive_shared_utm
        # (zone from the FIRST valid USBL fix) was superseded by 169ca4a's
        # pin_utm_projection (zone from the MEDIAN fix, robust to a bad
        # leading row -- the NA165 H2060 failure). The point of this test is
        # unchanged: both sources are converted in ONE frame across a zone
        # boundary, and USBL (absolute) chooses the frame over DVL
        # (dead-reckoned).
        from processors.kalman_filter import pin_utm_projection, latlon_to_utm
        # USBL just west of the 138E zone 53/54 boundary, DVL just east:
        # independent derivation would put them in different zones.
        df = pd.DataFrame({
            "Lat_USBL": [5.0], "Long_USBL": [137.995],
            "Lat_DVL": [5.0], "Long_DVL": [138.005],
        })
        proj, zone, hemi, _, _ = pin_utm_projection(
            df, [("Lat_USBL", "Long_USBL"), ("Lat_DVL", "Long_DVL")])
        assert (zone, hemi) == (53, "north")  # pinned from USBL, not DVL
        n_usbl, usbl_off = latlon_to_utm(
            df, "Lat_USBL", "Long_USBL", "x_usbl", "y_usbl", proj, zone)
        n_dvl, dvl_off = latlon_to_utm(
            df, "Lat_DVL", "Long_DVL", "x_dvl", "y_dvl", proj, zone)
        assert n_usbl == 1 and n_dvl == 1
        assert usbl_off == 0 and dvl_off == 1  # DVL naturally sits in zone 54
        x_usbl = df["x_usbl"].iloc[0]
        x_dvl = df["x_dvl"].iloc[0]
        # Same frame: ~1.1 km apart, NOT ~665 km (which a per-source zone
        # derivation would produce: easting 833k in zone 53 vs 168k in 54).
        assert abs(x_dvl - x_usbl) < 5000
        assert x_dvl > 700000  # east edge of zone 53, not west edge of 54

    def test_kalman_filter_writes_utm_zone_column(self, tmp_path):
        from processors import kalman_filter
        processed = make_processed_dir(tmp_path)
        write_filtered_datatable(processed, usbl_lon=133.995, dvl_lon=134.005)
        rc = kalman_filter.process_data(processed, processed)
        assert not rc
        final = pd.read_csv(processed / "NA167_H2075_final_datatable.csv")
        assert "utm_zone" in final.columns
        assert set(final["utm_zone"]) == {"53N"}

    def test_offset_reuses_stored_zone(self, capsys):
        from processors.kalman_offset import resolve_utm_zone
        df = pd.DataFrame({
            "utm_zone": ["53N", "53N"],
            "kalman_lat": [5.0, 5.0],
            "kalman_long": [133.9, 133.9],
        })
        assert resolve_utm_zone(df) == "53N"
        assert "recorded by kalman_filter" in capsys.readouterr().out

    def test_offset_errors_on_zone_mismatch(self):
        from processors.kalman_offset import resolve_utm_zone
        df = pd.DataFrame({
            "utm_zone": ["54N"],
            "kalman_lat": [5.0],
            "kalman_long": [133.9],  # derives 53N
        })
        with pytest.raises(ValueError, match="mismatch"):
            resolve_utm_zone(df)

    def test_offset_errors_on_conflicting_stored_zones(self):
        from processors.kalman_offset import resolve_utm_zone
        df = pd.DataFrame({
            "utm_zone": ["53N", "54N"],
            "kalman_lat": [np.nan, np.nan],
            "kalman_long": [np.nan, np.nan],
        })
        with pytest.raises(ValueError, match="conflicting"):
            resolve_utm_zone(df)

    def test_offset_falls_back_to_rederivation(self, capsys):
        from processors.kalman_offset import resolve_utm_zone
        df = pd.DataFrame({  # old datatable: no utm_zone column
            "kalman_lat": [5.0],
            "kalman_long": [133.9],
        })
        assert resolve_utm_zone(df) == "53N"
        assert "re-derived" in capsys.readouterr().out

    def test_offset_errors_when_zone_undeterminable(self):
        from processors.kalman_offset import resolve_utm_zone
        df = pd.DataFrame({"kalman_lat": [np.nan], "kalman_long": [np.nan]})
        with pytest.raises(ValueError, match="Cannot determine"):
            resolve_utm_zone(df)

    def test_proj_string_for_zone_label(self):
        assert "+zone=53 +north" in proj_string_for_zone_label("53N")
        assert "+zone=4 +south" in proj_string_for_zone_label("4S")
        with pytest.raises(ValueError):
            proj_string_for_zone_label("banana")
        with pytest.raises(ValueError):
            proj_string_for_zone_label("61N")


# ---------------------------------------------------------------------------
# FIX 1d -- PermissionError fallback writes the prefixed path, never cwd
# ---------------------------------------------------------------------------

class TestPermissionFallback:
    def test_fallback_lands_on_prefixed_path_not_cwd(self, monkeypatch, tmp_path):
        from processors import kalman_filter
        processed = make_processed_dir(tmp_path)
        write_filtered_datatable(processed)
        target_name = "NA167_H2075_kalman_filtered_data.csv"

        real_to_csv = pd.DataFrame.to_csv
        calls = {"denied": 0}

        def fake_to_csv(self, path_or_buf=None, *args, **kwargs):
            if isinstance(path_or_buf, Path) and path_or_buf.name == target_name:
                calls["denied"] += 1
                raise PermissionError("simulated lock")
            return real_to_csv(self, path_or_buf, *args, **kwargs)

        monkeypatch.setattr(pd.DataFrame, "to_csv", fake_to_csv)
        rc = kalman_filter.process_data(processed, processed)
        assert not rc
        assert calls["denied"] == 1
        out = processed / target_name
        assert out.exists() and out.stat().st_size > 0  # temp+rename landed
        assert not (out.parent / (target_name + ".tmp")).exists()
        # The old bug: an unprefixed orphan in the cwd that nothing reads.
        assert not (Path.cwd() / "kalman_filtered_data.csv").exists()


# ---------------------------------------------------------------------------
# FIX 4 -- SDYN midnight-rollover heuristic
# ---------------------------------------------------------------------------

class TestRolloverHeuristic:
    def test_fix_seconds_before_file_minute_stays_same_day(self, tmp_path):
        # 11:59:58 in a _1200 file: 2 s behind the filename minute -- NOT a
        # midnight wrap. The old `< file_start` test stamped this +24h.
        f = tmp_path / "20241105_1200.SDYN"
        f.write_text(gpgga("115958.00") + "\n")
        df = parse_sdyn_file(f)
        assert df.iloc[0]["Timestamp"] == pd.Timestamp("2024-11-05T11:59:58Z")

    def test_genuine_midnight_wrap_advances_a_day(self, tmp_path):
        f = tmp_path / "20241105_2359.SDYN"
        f.write_text(gpgga("235959.00") + "\n" + gpgga("000010.00") + "\n")
        df = parse_sdyn_file(f)
        assert df.iloc[0]["Timestamp"] == pd.Timestamp("2024-11-05T23:59:59Z")
        assert df.iloc[1]["Timestamp"] == pd.Timestamp("2024-11-06T00:00:10Z")

    def test_fix_after_file_start_unchanged(self, tmp_path):
        f = tmp_path / "20241105_2310.SDYN"
        f.write_text(gpgga("231205.50") + "\n")
        df = parse_sdyn_file(f)
        assert df.iloc[0]["Timestamp"] == pd.Timestamp("2024-11-05T23:12:05.5Z")


# ---------------------------------------------------------------------------
# FIX 5 -- dive-summary TSV validation
# ---------------------------------------------------------------------------

STATS_HEADER = ("##NA167\tdive\tsite\tinwatertime\tonbottomtime\toffbottomtime"
                "\tondecktime\thercmaxdepth\thercavgdepth\ttotaltime(hours)"
                "\tbottomtime(hours)")


def write_dive(tmp_path, dive="H2075", row_suffix="", times=None):
    folder = tmp_path / dive
    folder.mkdir()
    t = times or ("2024-11-05T23:13:02Z", "2024-11-06T00:08:00Z",
                  "2024-11-07T00:10:00Z", "2024-11-07T01:37:00Z")
    row = (f"NA167\t{dive}\tSome_Site\t{t[0]}\t{t[1]}"
           f"\t{t[2]}\t{t[3]}\t-1327.1\t-1005.0"
           f"\t26.4\t20.0{row_suffix}")
    (folder / f"{dive}-stats.tsv").write_text(STATS_HEADER + "\n" + row + "\n")
    (folder / f"{dive}-summary.txt").write_text("Objective: Map the site.\n")
    return folder


class TestDiveSummaryValidation:
    def test_trailing_tab_raises_loudly(self, tmp_path):
        folder = write_dive(tmp_path, row_suffix="\t")
        with pytest.raises(ValueError, match=r"line 2.*12 fields.*11 columns"):
            process_dive_folder(folder, "H2075")

    def test_missing_field_raises_loudly(self, tmp_path):
        folder = tmp_path / "H2075"
        folder.mkdir()
        row = "NA167\tH2075\tSome_Site\t2024-11-05T23:13:02Z"  # 4 of 11 fields
        (folder / "H2075-stats.tsv").write_text(STATS_HEADER + "\n" + row + "\n")
        (folder / "H2075-summary.txt").write_text("Objective: x\n")
        with pytest.raises(ValueError, match="4 fields"):
            process_dive_folder(folder, "H2075")

    def test_out_of_order_times_raise(self, tmp_path):
        # Recovery before Off Bottom -> chronology error, not a warning.
        folder = write_dive(tmp_path, times=(
            "2024-11-05T23:13:02Z", "2024-11-06T00:08:00Z",
            "2024-11-07T00:10:00Z", "2024-11-06T23:00:00Z"))
        with pytest.raises(ValueError, match="out of order"):
            process_dive_folder(folder, "H2075")

    def test_well_formed_dive_still_parses(self, tmp_path):
        folder = write_dive(tmp_path)
        df = process_dive_folder(folder, "H2075")
        assert df is not None
        assert df.iloc[0]["Recovery Time"] == "2024-11-07T01:37:00Z"


# ---------------------------------------------------------------------------
# FIX 6 -- VFR / OCT range gates
# ---------------------------------------------------------------------------

class TestRangeGates:
    def test_out_of_range_lat_rejected_and_counted(self, tmp_path):
        f = tmp_path / "test.DAT"
        # lat 133.948 (the swapped-field case the review reproduced)
        f.write_text(vfr_line(lon=5.672, lat=133.948) + "\n"
                     + vfr_line() + "\n")
        stats = {}
        _, vfr_df = parse_dat_file_both(f, stats=stats)
        assert len(vfr_df) == 1
        assert stats["vfr_range_rejects"] == 1

    def test_exact_zero_lat_or_lon_rejected(self, tmp_path):
        f = tmp_path / "test.DAT"
        f.write_text(vfr_line(lon=0.0, lat=5.672) + "\n"
                     + vfr_line(lon=133.948, lat=0.0) + "\n")
        stats = {}
        _, vfr_df = parse_dat_file_both(f, stats=stats)
        assert vfr_df.empty
        assert stats["vfr_range_rejects"] == 2

    def test_out_of_range_lon_rejected(self, tmp_path):
        f = tmp_path / "test.DAT"
        f.write_text(vfr_line(lon=181.5, lat=5.672) + "\n")
        stats = {}
        _, vfr_df = parse_dat_file_both(f, stats=stats)
        assert vfr_df.empty
        assert stats["vfr_range_rejects"] == 1

    def test_out_of_range_heading_rejected_and_counted(self, tmp_path):
        f = tmp_path / "test.DAT"
        f.write_text(oct_line(heading=400.0) + "\n"
                     + oct_line(heading=-5.0) + "\n"
                     + oct_line(heading=359.9) + "\n"
                     + oct_line(heading=0.0) + "\n")
        stats = {}
        oct_df, _ = parse_dat_file_both(f, stats=stats)
        assert len(oct_df) == 2  # 359.9 and 0.0 are valid
        assert stats["oct_heading_rejects"] == 2

    def test_null_island_region_still_rejected_and_counted(self, tmp_path):
        f = tmp_path / "test.DAT"
        f.write_text(vfr_line(lon=0.001, lat=-0.002) + "\n")
        stats = {}
        _, vfr_df = parse_dat_file_both(f, stats=stats)
        assert vfr_df.empty
        assert stats["vfr_range_rejects"] == 1


# ---------------------------------------------------------------------------
# FIX 7 -- case-insensitive double-glob dedupe
# ---------------------------------------------------------------------------

class TestGlobDedupe:
    def test_sdyn_files_counted_once(self, tmp_path):
        datalog = tmp_path / "raw" / "datalog"
        datalog.mkdir(parents=True)
        (datalog / "20241105_2310.SDYN").write_text(gpgga("231205.50") + "\n")
        df = process_all_sdyn_files(tmp_path)
        assert len(df) == 1  # was 2 on Windows (case-insensitive double glob)

    def test_dat_files_counted_once(self, tmp_path):
        navest = tmp_path / "raw" / "nav" / "navest"
        navest.mkdir(parents=True)
        (navest / "20241105.DAT").write_text(oct_line() + "\n" + vfr_line() + "\n")
        all_oct, all_vfr, _ = process_all_dat_files_both(tmp_path)
        assert len(all_oct) == 1
        assert len(all_vfr) == 1
