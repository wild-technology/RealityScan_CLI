from pathlib import Path
import re
import csv
import pandas as pd
from datetime import datetime, timezone, timedelta

from .common import best_fix_per_second, drop_duplicate_timestamps
from .report import RunReport

# ------------------------------------------------------------------------------
# Function: split_lat_long
# ------------------------------------------------------------------------------
def split_lat_long(df, column_name):
    """
    Splits a column containing a combined latitude-longitude string (separated by a space)
    into two separate numeric columns: {column_name}_lat and {column_name}_long.
    """
    if column_name in df.columns:
        df[[f"{column_name}_lat", f"{column_name}_long"]] = (
            df[column_name].str.split(" ", expand=True).astype(float)
        )
        df.drop(columns=[column_name], inplace=True)
        old_cols = list(df.columns)
        lat_col, long_col = f"{column_name}_lat", f"{column_name}_long"
        for c in [lat_col, long_col]:
            if c in old_cols:
                old_cols.remove(c)
        old_cols.append(lat_col)
        old_cols.append(long_col)
        df = df[old_cols]
    return df

# ------------------------------------------------------------------------------
# Function: extract_objective
# ------------------------------------------------------------------------------
def extract_objective(summary_filepath):
    """
    Extracts the objective text from a summary file.
    Reads each line until one starting with 'Objective:' is found.
    """
    try:
        with summary_filepath.open("r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("Objective:"):
                    return line[len("Objective:"):].strip()
    except Exception as e:
        print(f"Error reading summary file {summary_filepath}: {e}")
    return ""

# ------------------------------------------------------------------------------
# Function: convert_to_iso
# ------------------------------------------------------------------------------
def convert_to_iso(dt_series):
    """
    Converts a Pandas Series of datetimes to ISO8601 format (UTC) without sub-seconds.
    """
    return dt_series.apply(
        lambda dt: dt.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ") if pd.notnull(dt) else dt
    )

# ------------------------------------------------------------------------------
# Function: parse_dat_file_both
# ------------------------------------------------------------------------------
def parse_dat_file_both(filepath, stats=None):
    """
    Opens a .DAT file once and extracts two sets of data:
      - OCT lines (Hercules pitch/roll/heading)
      - VFR lines (Hercules lat/long with fix type SOLN_DEADRECK)

    Returns two DataFrames:
      oct_df: columns=["Timestamp", "Heading", "Pitch", "Roll"]
      vfr_df: columns=["Timestamp", "Longitude", "Latitude"]

    If ``stats`` (a dict) is given, per-file reject counts are accumulated
    into it under "vfr_range_rejects" and "oct_heading_rejects" so the run
    report can surface them.
    """
    # Regex for OCT lines
    oct_pattern = re.compile(
        r'^OCT\s+(\d{4}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d+\.\d+)\s+Hercules\s+'
        r'[\-\d.]+\s+[\-\d.]+\s+[\-\d.]+\s+'
        r'([\-\d.]+)\s+([\-\d.]+)\s+([\-\d.]+)\s+'
        r'[\-\d.]+\s+[\-\d.]+\s+[\-\d.]+\s+'
        r'([\-\d.]+)\s+([\-\d.]+)\s+([\-\d.]+)\s+'
        r'([\-\d.]+)\s+([\-\d.]+)\s+([\-\d.]+)'
    )
    # Regex for VFR lines
    vfr_pattern = re.compile(
        r"^VFR\s+(\d{4}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2}\.\d+)\s+(\d+)\s+(\d+)\s+(\S+)\s+([-\d.]+)\s+([-\d.]+)"
    )

    oct_data = []
    vfr_data = []
    malformed_lines = 0
    vfr_range_rejects = 0
    oct_heading_rejects = 0

    with filepath.open('r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            line_str = line.strip()
            if not line_str:
                continue

            # Check for OCT match
            oct_match = oct_pattern.match(line_str)
            if oct_match:
                date_str, time_str = oct_match.group(1), oct_match.group(2)
                dt_str = f"{date_str} {time_str}"
                try:
                    try:
                        dt = datetime.strptime(dt_str, "%Y/%m/%d %H:%M:%S.%f")
                    except ValueError:
                        dt = datetime.strptime(dt_str, "%Y/%m/%d %H:%M:%S")
                except ValueError:
                    malformed_lines += 1  # e.g. second field of 60+
                    continue
                dt = dt.replace(tzinfo=timezone.utc)
                heading, pitch, roll = map(float, oct_match.group(3, 4, 5))
                # Heading range gate: a compass heading must be in [0, 360).
                # Anything else is a sensor glitch or a shifted field; reject
                # the row and count it rather than feeding it downstream.
                if not (0.0 <= heading < 360.0):
                    oct_heading_rejects += 1
                    continue
                oct_data.append([dt, heading, pitch, roll])
                continue

            # Check for VFR match
            vfr_match = vfr_pattern.match(line_str)
            if vfr_match:
                vehicle_number = vfr_match.group(4)
                fix_type = vfr_match.group(5)
                if vehicle_number != "0" or fix_type != "SOLN_DEADRECK":
                    continue
                date_str, time_str = vfr_match.group(1), vfr_match.group(2)
                dt_str = f"{date_str} {time_str}"
                try:
                    try:
                        dt = datetime.strptime(dt_str, "%Y/%m/%d %H:%M:%S.%f")
                    except ValueError:
                        dt = datetime.strptime(dt_str, "%Y/%m/%d %H:%M:%S")
                except ValueError:
                    malformed_lines += 1
                    continue
                dt = dt.replace(tzinfo=timezone.utc)
                lon_str = vfr_match.group(6)
                lat_str = vfr_match.group(7)
                try:
                    lon_val = float(lon_str)
                    lat_val = float(lat_str)
                except ValueError:
                    continue
                # Range gate: latitude must be in [-90, 90], longitude in
                # [-180, 180], and exact 0.0 in either is an uninitialized
                # fix (null island axis), not a real position. A swapped or
                # shifted field (e.g. lat 133.9) must not reach the filter.
                if (not (-90.0 <= lat_val <= 90.0)
                        or not (-180.0 <= lon_val <= 180.0)
                        or lat_val == 0.0 or lon_val == 0.0):
                    vfr_range_rejects += 1
                    continue
                # Near-null-island gate (pre-existing): dead-reckon seeds
                # near (0, 0) are bogus even when not exactly zero.
                if abs(lon_val) < 1 and abs(lat_val) < 1:
                    vfr_range_rejects += 1
                    continue
                vfr_data.append([dt, lon_str, lat_str])

    if malformed_lines:
        print(f"  - Skipped {malformed_lines} lines with unparseable timestamps in {filepath.name}")
    if vfr_range_rejects:
        print(f"  - Rejected {vfr_range_rejects} VFR fixes with out-of-range/zero "
              f"lat-long in {filepath.name}")
    if oct_heading_rejects:
        print(f"  - Rejected {oct_heading_rejects} OCT rows with out-of-range "
              f"heading in {filepath.name}")
    if stats is not None:
        stats["vfr_range_rejects"] = stats.get("vfr_range_rejects", 0) + vfr_range_rejects
        stats["oct_heading_rejects"] = stats.get("oct_heading_rejects", 0) + oct_heading_rejects

    oct_df = pd.DataFrame(oct_data, columns=["Timestamp", "Heading", "Pitch", "Roll"])
    vfr_df = pd.DataFrame(vfr_data, columns=["Timestamp", "Longitude", "Latitude"])
    return oct_df, vfr_df

# ------------------------------------------------------------------------------
# Function: process_all_dat_files_both
# ------------------------------------------------------------------------------
def process_all_dat_files_both(root_dir, *, files=None):
    """
    Iterates over all .DAT files in <root_dir>/raw/nav/navest/ and extracts both OCT and VFR data.

    Returns two DataFrames: one for OCT and one for VFR.
    """
    root_dir = Path(root_dir)  # Convert to Path if it's a string
    navest_dir = root_dir / "raw" / "nav" / "navest"
    if not navest_dir.exists():
        raise FileNotFoundError(f"NavEst directory not found at {navest_dir}")

    # Set union: Windows globbing is case-insensitive, so concatenating the
    # two glob lists double-counted every file (doubling parse metrics).
    # Sorted for deterministic processing order.
    all_files = (sorted(set(files)) if files is not None else
                 sorted(set(navest_dir.glob("*.dat")) | set(navest_dir.glob("*.DAT"))))
    all_oct = pd.DataFrame()
    all_vfr = pd.DataFrame()
    stats = {"vfr_range_rejects": 0, "oct_heading_rejects": 0}

    for filepath in all_files:
        oct_df, vfr_df = parse_dat_file_both(filepath, stats=stats)
        if not oct_df.empty:
            all_oct = pd.concat([all_oct, oct_df], ignore_index=True)
        if not vfr_df.empty:
            all_vfr = pd.concat([all_vfr, vfr_df], ignore_index=True)

    if not all_oct.empty:
        all_oct.sort_values("Timestamp", inplace=True)
    if not all_vfr.empty:
        all_vfr.sort_values("Timestamp", inplace=True)

    return all_oct, all_vfr, stats

# ------------------------------------------------------------------------------
# Function: preserve_closest_fix_per_second
# ------------------------------------------------------------------------------
def preserve_closest_fix_per_second(df):
    """
    Rounds timestamps to the nearest second and, for each unique second,
    retains the row closest to that second (shared implementation in
    processors.common). Returns (df, orig_count, final_count, duplicates_removed).
    """
    if df.empty:
        return df, 0, 0, 0
    df_unique, orig_count, final_count = best_fix_per_second(df)
    return df_unique, orig_count, final_count, orig_count - final_count

# ------------------------------------------------------------------------------
# Function: remove_timestamp_duplicates
# ------------------------------------------------------------------------------
def remove_timestamp_duplicates(df):
    """Shared duplicate-timestamp removal (see processors.common)."""
    return drop_duplicate_timestamps(df)

# ------------------------------------------------------------------------------
# Function: process_dive_vehicle_rows_oct
# ------------------------------------------------------------------------------
def process_dive_vehicle_rows_oct(dive_info, oct_data):
    """
    Filters the OCT data to the dive window defined by [Launch Time, Recovery Time],
    and deduplicates fixes by rounding timestamps.
    """
    dive_id = str(dive_info["dive"]).strip()
    launch = dive_info["Launch Time"]
    recovery = dive_info["Recovery Time"]

    if pd.isnull(launch) or pd.isnull(recovery):
        return pd.DataFrame(), 0, 0, 0, 0

    expected_seconds = int((recovery - launch).total_seconds())
    if expected_seconds < 0:
        return pd.DataFrame(), 0, 0, 0, 0

    df_sub = oct_data[
        (oct_data["Timestamp"] >= launch) &
        (oct_data["Timestamp"] <= recovery)
        ].copy()

    if df_sub.empty:
        return pd.DataFrame(), 0, 0, 0, expected_seconds

    df_rounded, orig_count, final_count, duplicates = preserve_closest_fix_per_second(df_sub)
    return df_rounded, orig_count, final_count, duplicates, expected_seconds

# ------------------------------------------------------------------------------
# Function: output_dive_csv_oct
# ------------------------------------------------------------------------------
def output_dive_csv_oct(root_dir, expedition_name, dive_id, df, *, output_dir=None):
    """
    Saves the OCT data (pitch/roll/heading) to a CSV file in <root_dir>/RUMI_processed/<dive_id>/.
    Performs a final check for duplicate timestamps before writing.
    """
    if df.empty:
        return None

    root_dir = Path(root_dir)  # Convert to Path if it's a string
    outdir = (Path(output_dir) if output_dir else root_dir / "RUMI_processed") / dive_id
    outdir.mkdir(parents=True, exist_ok=True)

    # Final check for duplicates
    df_final, dupes_removed = remove_timestamp_duplicates(df)
    if dupes_removed > 0:
        print(f"  - Final duplicate check: Removed {dupes_removed} duplicate timestamps")

    fname = f"{expedition_name}_{dive_id}_pitch_roll_heading_octans.csv"
    outpath = outdir / fname
    df_final.to_csv(outpath, index=False)
    print(f"Saved OCT data to: {outpath}")
    return outpath

# ------------------------------------------------------------------------------
# Function: process_dive_vehicle_rows_latlong
# ------------------------------------------------------------------------------
def process_dive_vehicle_rows_latlong(dive_info, vfr_data):
    """
    Filters VFR (lat/long) data to the window defined by [On Bottom Time, Off Bottom Time]
    and deduplicates fixes.
    """
    dive_id = str(dive_info["dive"]).strip()
    on_bottom = dive_info.get("On Bottom Time", None)
    off_bottom = dive_info.get("Off Bottom Time", None)

    if pd.isnull(on_bottom) or pd.isnull(off_bottom):
        return pd.DataFrame(), 0, 0, 0, 0

    if off_bottom < on_bottom:
        return pd.DataFrame(), 0, 0, 0, 0

    expected_seconds = int((off_bottom - on_bottom).total_seconds())
    df_sub = vfr_data[
        (vfr_data["Timestamp"] >= on_bottom) &
        (vfr_data["Timestamp"] <= off_bottom)
        ].copy()

    if df_sub.empty:
        return pd.DataFrame(), 0, 0, 0, expected_seconds

    df_rounded, orig_count, final_count, duplicates = preserve_closest_fix_per_second(df_sub)
    return df_rounded, orig_count, final_count, duplicates, expected_seconds

# ------------------------------------------------------------------------------
# Function: output_dive_csv_latlong
# ------------------------------------------------------------------------------
def output_dive_csv_latlong(root_dir, expedition_name, dive_id, df, *, output_dir=None):
    """
    Saves DVL lat/long data to a CSV file in <root_dir>/RUMI_processed/<dive_id>/.
    The output columns are ordered: Timestamp, Latitude, Longitude.
    Performs a final check for duplicate timestamps before writing.
    """
    if df.empty:
        return None

    root_dir = Path(root_dir)  # Convert to Path if it's a string
    outdir = (Path(output_dir) if output_dir else root_dir / "RUMI_processed") / dive_id
    outdir.mkdir(parents=True, exist_ok=True)

    desired_cols = ["Timestamp", "Latitude", "Longitude"]
    for col in desired_cols:
        if col not in df.columns:
            return None
    df = df[desired_cols]

    # Final check for duplicates
    df_final, dupes_removed = remove_timestamp_duplicates(df)
    if dupes_removed > 0:
        print(f"  - Final duplicate check: Removed {dupes_removed} duplicate timestamps")

    fname = f"{expedition_name}_{dive_id}_dvl_lat_long.csv"
    outpath = outdir / fname
    df_final.to_csv(outpath, index=False)
    print(f"Saved DVL lat/long data to: {outpath}")
    return outpath

# ------------------------------------------------------------------------------
# Main process_data
# ------------------------------------------------------------------------------
def process_data(root_dir, *, output_dir=None, files=None):
    """
    Processes the .DAT files using dive time windows from the existing dive summaries CSV.
    Assumes dive summaries are available at <root_dir>/RUMI_processed/all_dive_summaries.csv.

    For each dive summary:
      - OCT data is filtered using Launch Time and Recovery Time.
      - VFR (DVL lat/long) data is filtered using On Bottom Time and Off Bottom Time.

    Results are saved as CSVs in <root_dir>/RUMI_processed/<dive_id>/.
    """
    root_dir = Path(root_dir)  # Convert to Path if it's a string
    output_dir = Path(output_dir) if output_dir else root_dir / "RUMI_processed"
    summary_path = output_dir / "all_dive_summaries.csv"

    if not summary_path.exists():
        print(f"Error: Dive summary file not found at {summary_path}")
        return

    try:
        ds = pd.read_csv(summary_path)
        ds["Launch Time"] = pd.to_datetime(ds["Launch Time"], utc=True, errors="coerce")
        ds["Recovery Time"] = pd.to_datetime(ds["Recovery Time"], utc=True, errors="coerce")
        if "On Bottom Time" in ds.columns:
            ds["On Bottom Time"] = pd.to_datetime(ds["On Bottom Time"], utc=True, errors="coerce")
        if "Off Bottom Time" in ds.columns:
            ds["Off Bottom Time"] = pd.to_datetime(ds["Off Bottom Time"], utc=True, errors="coerce")
    except Exception as e:
        print(f"Error reading dive summaries: {e}")
        return

    report = RunReport("process_dat", output_dir)

    print("\nReading all .DAT files once to capture both OCT and VFR data...")
    all_oct, all_vfr, parse_stats = process_all_dat_files_both(root_dir, files=files)
    report.metric("oct_records_parsed", len(all_oct))
    report.metric("vfr_records_parsed", len(all_vfr))
    report.metric("vfr_fixes_rejected_range", parse_stats["vfr_range_rejects"])
    report.metric("oct_rows_rejected_heading_range", parse_stats["oct_heading_rejects"])
    if parse_stats["vfr_range_rejects"]:
        report.warn("vfr-range-rejects",
                    f"{parse_stats['vfr_range_rejects']} VFR fixes rejected by the "
                    f"lat/long range gate (out of range or exactly zero)")
    if parse_stats["oct_heading_rejects"]:
        report.warn("oct-heading-rejects",
                    f"{parse_stats['oct_heading_rejects']} OCT rows rejected by the "
                    f"heading range gate (outside [0, 360))")
    if all_oct.empty and all_vfr.empty:
        print("No OCT or VFR data found in any .DAT file.")
        report.error("no-data", "no OCT or VFR records found in any .DAT file")
        report.finalize()
        return

    print("\n=== Processing Dives ===")
    total_oct_fixes = 0
    total_oct_expected = 0
    total_vfr_fixes = 0
    total_vfr_expected = 0

    for _, row in ds.iterrows():
        expedition = str(row.get("expedition", "NA")).strip()
        dive_id = str(row.get("dive", "UNKNOWN")).strip()

        df_oct, orig_oct, final_oct, dup_oct, exp_oct = process_dive_vehicle_rows_oct(row, all_oct)
        total_oct_expected += exp_oct
        if not df_oct.empty:
            written = output_dive_csv_oct(root_dir, expedition, dive_id, df_oct, output_dir=output_dir)
            report.add_output(written, rows=len(df_oct))
            total_oct_fixes += final_oct
            coverage_oct = (final_oct / exp_oct * 100) if exp_oct else 0
            print(f"\n(OCT) Dive {dive_id} Summary:")
            print(f"  - Duration: {exp_oct} seconds")
            print(f"  - Original Fixes: {orig_oct}")
            print(f"  - After Rounding: {final_oct}")
            print(f"  - Duplicates Removed: {dup_oct}")
            print(f"  - Coverage: {coverage_oct:.2f}%")
            if coverage_oct < 90:
                report.anomaly("low-coverage",
                               f"dive {dive_id}: OCT coverage only {coverage_oct:.1f}% "
                               f"of the dive window")
        else:
            print(f"WARNING: Dive {dive_id}: No OCT data within the defined window.")
            report.warn("no-data", f"dive {dive_id}: no OCT data in the dive window")

        df_vfr, orig_vfr, final_vfr, dup_vfr, exp_vfr = process_dive_vehicle_rows_latlong(row, all_vfr)
        total_vfr_expected += exp_vfr
        if not df_vfr.empty:
            written = output_dive_csv_latlong(root_dir, expedition, dive_id, df_vfr, output_dir=output_dir)
            report.add_output(written, rows=len(df_vfr))
            total_vfr_fixes += final_vfr
            coverage_vfr = (final_vfr / exp_vfr * 100) if exp_vfr else 0
            print(f"\n(LAT/LONG) Dive {dive_id} Summary:")
            print(f"  - Duration: {exp_vfr} seconds")
            print(f"  - Original Fixes: {orig_vfr}")
            print(f"  - After Rounding: {final_vfr}")
            print(f"  - Duplicates Removed: {dup_vfr}")
            print(f"  - Coverage: {coverage_vfr:.2f}%")
            if coverage_vfr < 90:
                report.anomaly("low-coverage",
                               f"dive {dive_id}: DVL coverage only {coverage_vfr:.1f}% "
                               f"of the on-bottom window")
        else:
            print(f"WARNING: Dive {dive_id}: No VFR data within the On Bottom/Off Bottom window.")
            report.warn("no-data", f"dive {dive_id}: no DVL data in the on-bottom window")

    print("\n=== Processing Complete! ===")
    print(f"* OCT total expected: {total_oct_expected} seconds, total fixes: {total_oct_fixes}")
    print(f"* VFR total expected: {total_vfr_expected} seconds, total fixes: {total_vfr_fixes}")
    print(f"Data stored in {output_dir}")

    report.metric("oct_fixes_written", total_oct_fixes)
    report.metric("vfr_fixes_written", total_vfr_fixes)
    report.finalize()

# ------------------------------------------------------------------------------
# End of Script
# ------------------------------------------------------------------------------
