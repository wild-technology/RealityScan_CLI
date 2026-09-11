from pathlib import Path
import numpy as np
import pandas as pd
import csv

from .common import expedition_dive_from_processed_dir, find_time_gaps
from .report import RunReport


def remove_duplicate_timestamps_prioritizing_event(df):
    """
    Removes duplicate rows in df based on the 'Timestamp' column.
    For each group of rows sharing the same Timestamp, it prioritizes keeping
    the row where the 'event_value' column is not null (if available).
    The result stays in chronological order.

    Returns:
      new_df (pd.DataFrame): DataFrame with duplicates removed.
      duplicate_counts (dict): Timestamp -> number of duplicates removed.
      total_removed (int): Total number of rows removed.
    """
    dup_sizes = df.groupby("Timestamp").size()
    duplicate_counts = {ts: n - 1 for ts, n in dup_sizes.items() if n > 1}

    if "event_value" in df.columns:
        # Stable sort: rows with a non-null event_value come first within each
        # timestamp, then keep the first row per timestamp.
        order = df["event_value"].isnull()
        new_df = (
            df.assign(_no_event=order)
            .sort_values(["Timestamp", "_no_event"], kind="mergesort")
            .drop_duplicates(subset=["Timestamp"], keep="first")
            .drop(columns=["_no_event"])
        )
    else:
        new_df = df.sort_values("Timestamp", kind="mergesort").drop_duplicates(
            subset=["Timestamp"], keep="first"
        )

    total_removed = df.shape[0] - new_df.shape[0]
    return new_df, duplicate_counts, total_removed


def process_data(raw_dir, processed_dir):
    """
    Merges various navigation data sources for ROV navigation, applies an outlier filter for
    pitch and roll values based on mean and standard deviation, and removes duplicate timestamps
    prioritizing non-null event_value rows.

    Parameters
    ----------
    raw_dir : Path or str
        Directory containing the input files. This path should already include the dive folder.
    processed_dir : Path or str
        Directory where the output file will be saved.
    """
    # Convert to Path objects and resolve to absolute paths.
    raw_dir = Path(raw_dir).resolve()
    processed_dir = Path(processed_dir).resolve()

    expedition, dive = expedition_dive_from_processed_dir(processed_dir)

    print("Running Kalman Concat Process...")

    # Dynamically build the filenames based on expedition and dive.
    usbl_file = processed_dir / f"{expedition}_{dive}_USBL_Hercules.csv"
    octans_file = processed_dir / f"{expedition}_{dive}_pitch_roll_heading_octans.csv"
    dvl_file = processed_dir / f"{expedition}_{dive}_dvl_lat_long.csv"
    depth_file = processed_dir / f"{expedition}_{dive}_sealog_sensors_merged.csv"
    output_file = processed_dir / f"{expedition}_{dive}_filtered_datatable.csv"

    def read_nav_csv(path, label, required=False):
        """Read one navigation CSV; missing optional inputs return None."""
        if not path.exists():
            msg = f"{label} file not found: {path}"
            if required:
                raise FileNotFoundError(msg)
            print(f"Warning: {msg} -- continuing without it.")
            return None
        return pd.read_csv(path, parse_dates=["Timestamp"], low_memory=False,
                           quotechar='"').sort_values("Timestamp")

    report = RunReport("kalman_concat", processed_dir)

    # Octans (heading/pitch/roll) and the merged sensor file are essential;
    # USBL and DVL can legitimately be absent for a dive.
    octans_df = read_nav_csv(octans_file, "Octans", required=True)
    depth_df = read_nav_csv(depth_file, "Sealog/sensor merge", required=True)
    usbl_df = read_nav_csv(usbl_file, "USBL")
    dvl_df = read_nav_csv(dvl_file, "DVL")

    for label, frame, path in (("octans", octans_df, octans_file),
                               ("sensors", depth_df, depth_file),
                               ("usbl", usbl_df, usbl_file),
                               ("dvl", dvl_df, dvl_file)):
        if frame is not None:
            report.add_input(path, rows=len(frame))
        else:
            report.warn("missing-input", f"{label} file absent: {path.name}")

    # Rename columns for clarity
    if usbl_df is not None:
        usbl_df.rename(columns={"Latitude": "Lat_USBL", "Longitude": "Long_USBL",
                                "Accuracy": "Accuracy_USBL"}, inplace=True)
    if dvl_df is not None:
        dvl_df.rename(columns={"Latitude": "Lat_DVL", "Longitude": "Long_DVL"}, inplace=True)

    # Merge all available datasets using outer join on Timestamp
    merged_df = octans_df
    for other in (usbl_df, dvl_df, depth_df):
        if other is not None:
            merged_df = pd.merge(merged_df, other, on="Timestamp", how="outer")
    # Keep downstream column expectations stable even when a source is absent.
    for col in ("Lat_USBL", "Long_USBL", "Accuracy_USBL", "Lat_DVL", "Long_DVL"):
        if col not in merged_df.columns:
            merged_df[col] = float("nan")
    merged_df.sort_values("Timestamp", inplace=True)

    print(f"Merged dataframe shape before filtering: {merged_df.shape}")

    # Identify pitch and roll columns in a case-insensitive way
    pitch_col = next((col for col in merged_df.columns if col.lower() == "pitch"), None)
    roll_col = next((col for col in merged_df.columns if col.lower() == "roll"), None)

    # Initialize outlier counts per column
    pitch_outlier_count = 0
    roll_outlier_count = 0

    if pitch_col or roll_col:
        outlier_mask = pd.Series(False, index=merged_df.index)
        threshold = 3  # Using 3 standard deviations as cutoff

        if pitch_col:
            pitch_mean = merged_df[pitch_col].mean()
            pitch_std = merged_df[pitch_col].std()
            pitch_outliers = (merged_df[pitch_col] < pitch_mean - threshold * pitch_std) | \
                             (merged_df[pitch_col] > pitch_mean + threshold * pitch_std)
            pitch_outlier_count = pitch_outliers.sum()
            print(
                f"Pitch ({pitch_col}): mean = {pitch_mean:.4f}, std = {pitch_std:.4f}, outliers = {pitch_outlier_count}")
            outlier_mask |= pitch_outliers
        if roll_col:
            roll_mean = merged_df[roll_col].mean()
            roll_std = merged_df[roll_col].std()
            roll_outliers = (merged_df[roll_col] < roll_mean - threshold * roll_std) | \
                            (merged_df[roll_col] > roll_mean + threshold * roll_std)
            roll_outlier_count = roll_outliers.sum()
            print(f"Roll ({roll_col}): mean = {roll_mean:.4f}, std = {roll_std:.4f}, outliers = {roll_outlier_count}")
            outlier_mask |= roll_outliers

        total_outliers = int(outlier_mask.sum())
        # Null only the offending pitch/roll values -- do NOT drop the rows.
        # A pitch spike must not discard the row's USBL fix, sensor sample, or
        # sealog annotation (the previous behavior removed the whole row).
        if pitch_col:
            merged_df.loc[pitch_outliers, pitch_col] = np.nan
        if roll_col:
            merged_df.loc[roll_outliers, roll_col] = np.nan
        print(f"Nulled pitch/roll on {total_outliers} outlier rows (rows retained).")
        if total_outliers:
            report.warn("orientation-outliers",
                        f"{int(pitch_outlier_count)} pitch / {int(roll_outlier_count)} roll "
                        f"values beyond 3 sigma were nulled ({total_outliers} rows affected, kept)")
    else:
        print("No pitch/roll columns found for filtering.")
        report.warn("missing-columns", "no pitch/roll columns found in merged data")

    print(f"Merged dataframe shape after filtering: {merged_df.shape}")

    # Run duplicate timestamp check with priority for non-null event_value
    merged_df, duplicate_counts, total_removed = remove_duplicate_timestamps_prioritizing_event(merged_df)
    print(f"After duplicate removal prioritizing event_value, removed {total_removed} duplicate rows.")
    print(f"Merged dataframe shape after duplicate removal: {merged_df.shape}")

    # Optionally, print a sample of per-Timestamp duplicate counts
    if duplicate_counts:
        print("Duplicate counts per Timestamp (sample):")
        for ts, cnt in list(duplicate_counts.items())[:5]:
            print(f"  {ts}: {cnt} duplicates")
    else:
        print("No duplicate timestamps found.")

    if total_removed:
        report.warn("duplicate-timestamps",
                    f"{total_removed} duplicate-timestamp rows removed "
                    f"(kept rows with sealog events)")

    # Surface large holes in the merged timeline.
    gaps = find_time_gaps(merged_df["Timestamp"], max_gap_s=60)
    if gaps:
        top = ", ".join(f"{g[2]:.0f}s after {g[0]}" for g in gaps[:3])
        report.anomaly("time-gaps",
                       f"{len(gaps)} gaps > 60s in merged timeline (largest: {top})")

    # Convert Timestamp to ISO8601 with seconds only
    merged_df["Timestamp"] = merged_df["Timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Ensure the processed directory exists
    processed_dir.mkdir(parents=True, exist_ok=True)

    # Export to CSV with quoting enabled
    merged_df.to_csv(output_file, index=False, quoting=csv.QUOTE_ALL)
    print(f"Kalman merged data saved to: {output_file}")

    report.metric("rows_out", len(merged_df))
    report.add_output(output_file, rows=len(merged_df))
    report.finalize()
