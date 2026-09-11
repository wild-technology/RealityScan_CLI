from pathlib import Path
import pandas as pd
import csv

from .common import drop_duplicate_timestamps
from .report import RunReport

# ------------------------------------------------------------------------------
# Function: get_file_paths
# ------------------------------------------------------------------------------
def get_file_paths(base_directory, dive_number, *, reports_dir=None):
    """
    Constructs file paths for various datasets related to a specific dive.

    This function builds paths for the CTD file, Sealog file, dive summary file,
    and other related directories using the given base directory and dive number.
    It also extracts the expedition name from the base directory.

    Parameters:
      base_directory (Path or str): The root directory for the expedition.
      dive_number (str): The identifier for the specific dive.

    Returns:
      dict: A dictionary with keys:
          - "ctd": Path to the CTD sampled TSV file.
          - "sealog": Path to the Sealog CSV file.
          - "summary": Path to the dive summaries CSV.
          - "output_dir": The base directory (same as base_directory).
          - "expedition": The expedition name (last folder in base_directory).
          - "sampled_dir": The directory containing the sampled files for the dive.
    """
    # Convert base_directory to Path if it's a string
    base_directory = Path(base_directory)

    # Extract expedition name from the base directory.
    expedition = base_directory.name

    # Define the directory for sampled files for the given dive.
    reports_dir = Path(reports_dir) if reports_dir else base_directory / "processed" / "dive_reports"
    sampled_dir = reports_dir / dive_number / "sampled"

    return {
        "ctd": sampled_dir / f"{dive_number}.CTD.sampled.tsv",
        "sealog": base_directory / "raw" / "sealog" / "sealog-herc" / dive_number / f"{dive_number}_sealogExport.csv",
        "summary": base_directory / "RUMI_processed" / "all_dive_summaries.csv",
        "output_dir": base_directory,
        "expedition": expedition,
        "sampled_dir": sampled_dir,
    }

# ------------------------------------------------------------------------------
# Function: to_iso8601_str
# ------------------------------------------------------------------------------
def to_iso8601_str(dt_series):
    """
    Converts a Pandas Series of datetime values to ISO8601 format with a 'Z' suffix to indicate UTC.

    Parameters:
      dt_series (pd.Series): Series containing datetime values.

    Returns:
      pd.Series: Series where each datetime is converted to a string in the format:
                 "YYYY-MM-DDTHH:MM:SSZ".
    """
    return dt_series.dt.strftime("%Y-%m-%dT%H:%M:%SZ")

# ------------------------------------------------------------------------------
# Function: load_tsv_file
# ------------------------------------------------------------------------------
def load_tsv_file(file_path, sensor_name=None, enforce_negative=False, column_names=None, drop_temperature=False):
    """
    Loads a TSV file and processes its timestamps and sensor values.

    If 'column_names' is provided, the function only uses the first (1 + len(column_names))
    columns (the first column is assumed to be the Timestamp). Otherwise, it assigns column
    names based on the sensor name. The function converts the Timestamp column to a UTC datetime.
    Optionally, sensor values are forced to be negative (by taking their absolute value and negating)
    if enforce_negative is True. It can also drop a column named "Temperature" if requested.

    Parameters:
      file_path (Path or str): Path to the TSV file.
      sensor_name (str, optional): Sensor prefix to use for naming columns if 'column_names' is not provided.
      enforce_negative (bool, optional): If True, converts sensor values to negative values.
      column_names (list of str, optional): List of sensor-specific column names to assign.
      drop_temperature (bool, optional): If True, drops the "Temperature" column from the DataFrame.

    Returns:
      pd.DataFrame or None: Processed DataFrame with a Timestamp column and sensor columns,
                            or None if the file does not exist.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        return None
    try:
        df = pd.read_csv(file_path, sep="\t", header=None, quoting=csv.QUOTE_MINIMAL)

        # If column_names are provided, enforce the expected number of columns.
        if column_names:
            expected = 1 + len(column_names)
            if df.shape[1] > expected:
                df = df.iloc[:, :expected]
            elif df.shape[1] < expected:
                print(f"Warning: Expected {expected} columns, found {df.shape[1]} in {file_path}.")
            df.columns = ["Timestamp"] + column_names
        else:
            # If no column names provided, create default names based on sensor_name.
            df.columns = ["Timestamp"] + [f"{sensor_name}_{i + 1}" for i in range(df.shape[1] - 1)]

        # Convert the Timestamp column to datetime in UTC.
        df["Timestamp"] = pd.to_datetime(df["Timestamp"].astype(str).str.strip(), utc=True, errors="coerce")

        # Optionally enforce negative values for sensor columns.
        if enforce_negative:
            for col in df.columns[1:]:
                df[col] = -df[col].abs()

        # Optionally drop the Temperature column.
        if drop_temperature and "Temperature" in df.columns:
            df = df.drop(columns=["Temperature"], errors="ignore")

        # Remove duplicate timestamps
        orig_len = len(df)
        df = df.drop_duplicates(subset=["Timestamp"])
        dupes_removed = orig_len - len(df)
        if dupes_removed > 0:
            print(f"Removed {dupes_removed} duplicate timestamps from {file_path.name}")

        return df
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return None

# ------------------------------------------------------------------------------
# Function: load_sealog_file
# ------------------------------------------------------------------------------
def load_sealog_file(file_path):
    """
    Loads and processes a Sealog CSV file containing sensor data.

    The function:
      1) Reads the CSV file and attempts to retain only the desired columns.
      2) Renames the "ts" column to "Timestamp" if present.
      3) Converts the Timestamp to UTC datetime, rounding to the nearest second.
      4) Retains only rows where 'event_value' is either 'FREE_FORM' or 'HIGHLIGHT'.
      5) Removes duplicate timestamps.

    Parameters:
      file_path (Path or str): Path to the Sealog CSV file.

    Returns:
      pd.DataFrame or None: Processed DataFrame with a Timestamp column and selected sensor columns,
                            or None if the file does not exist (or could not be read).
    """
    file_path = Path(file_path)
    if not file_path.exists():
        return None
    try:
        desired_columns = [
            "ts", "event_value", "event_free_text", "event_option.channel", "event_option.milestone",
            "event_option.rating", "event_option.vehicle", "vehicleRealtimeDualHDGrabData.camera_name_2_uom",
            "vehicleRealtimeDualHDGrabData.camera_name_2_value", "vehicleRealtimeDualHDGrabData.camera_name_uom",
            "vehicleRealtimeDualHDGrabData.camera_name_value", "vehicleRealtimeDualHDGrabData.filename_2_uom",
            "vehicleRealtimeDualHDGrabData.filename_2_value", "vehicleRealtimeDualHDGrabData.filename_uom",
            "vehicleRealtimeDualHDGrabData.filename_value"
        ]
        df = pd.read_csv(file_path, low_memory=False, quoting=csv.QUOTE_MINIMAL)
        print(f"Loaded {len(df)} rows from Sealog: {file_path}")

        # Rename "ts" to "Timestamp" if present
        if "ts" in df.columns:
            df = df.rename(columns={"ts": "Timestamp"})

        # Retain only the desired columns that are available.
        available = [col for col in desired_columns if col in df.columns]
        if "Timestamp" not in available and "Timestamp" in df.columns:
            available = ["Timestamp"] + available
        df = df[available]

        # Parse the Timestamp column
        ts_str = df["Timestamp"].astype(str).str.strip()
        try:
            df["Timestamp"] = pd.to_datetime(ts_str, format="%Y-%m-%dT%H:%M:%S.%fZ", utc=True)
        except Exception:
            df["Timestamp"] = pd.to_datetime(ts_str, utc=True, errors="coerce")

        # Round timestamps to nearest second
        df["Timestamp"] = df["Timestamp"].dt.round("s")

        # Keep only event_value == 'FREE_FORM' or 'HIGHLIGHT'
        if "event_value" in df.columns:
            df = df[df["event_value"].isin(["FREE_FORM", "HIGHLIGHT"])]

        # Remove duplicate timestamps
        orig_len = len(df)
        df = df.drop_duplicates(subset=["Timestamp"])
        dupes_removed = orig_len - len(df)
        if dupes_removed > 0:
            print(f"Removed {dupes_removed} duplicate timestamps from Sealog file")

        return df

    except Exception as e:
        print(f"Error reading Sealog file {file_path}: {e}")
        return None

# ------------------------------------------------------------------------------
# Function: remove_timestamp_duplicates
# ------------------------------------------------------------------------------
def remove_timestamp_duplicates(df):
    """Shared duplicate-timestamp removal (see processors.common)."""
    return drop_duplicate_timestamps(df)

# ------------------------------------------------------------------------------
# Function: process_single_dive
# ------------------------------------------------------------------------------
def process_single_dive(root_dir, expedition, dive_number, report=None, *, output_dir=None, reports_dir=None):
    """
    Processes a single dive by merging various sensor datasets and saving the merged output.

    The Hercules-related data (DEP1) is merged with CTD, Sealog, and O2S into one file:
        <expedition>_<dive_number>_sealog_sensors_merged.csv

    The Atalanta-related data (DEP2) is loaded only from the TSV and saved "as-is" with raw columns:
        <expedition>_<dive_number>_USBL_Atalanta.csv

    Parameters:
      root_dir (Path or str): The base directory for processing.
      expedition (str): The expedition identifier (derived from the base directory name).
      dive_number (str): The dive identifier.
    """
    # Convert root_dir to Path if it's a string
    root_dir = Path(root_dir)

    # Create output directory for the dive.
    dive_output_dir = (Path(output_dir) if output_dir else root_dir / "RUMI_processed") / dive_number
    dive_output_dir.mkdir(parents=True, exist_ok=True)

    # Get file paths for the dive datasets.
    paths = get_file_paths(root_dir, dive_number, reports_dir=reports_dir)

    # Define expected column names for the CTD and O2S datasets.
    ctd_columns = ["Temperature", "Conductivity", "Pressure", "Salinity", "Sound_Velocity"]
    o2s_columns = ["O2_Concentration", "O2_Saturation"]

    # ----------------------------
    # Load CTD data (for Hercules)
    # ----------------------------
    ctd_df = load_tsv_file(paths["ctd"], sensor_name="CTD", column_names=ctd_columns)
    if ctd_df is None:
        print(f"Skipping {dive_number} due to missing CTD data.")
        if report:
            report.warn("missing-input",
                        f"dive {dive_number}: CTD file missing ({paths['ctd'].name}); dive skipped")
        return

    initial_rows = len(ctd_df)
    print(f"CTD dataset initial rows: {initial_rows}")

    # -------------------------
    # Load Sealog, Hercules, O2S
    # -------------------------
    sealog_df = load_sealog_file(paths["sealog"])
    herc_df = load_tsv_file(
        paths["sampled_dir"] / f"{dive_number}.DEP1.sampled.tsv",
        sensor_name="Herc_Depth",
        enforce_negative=True
    )
    o2s_df = load_tsv_file(
        paths["sampled_dir"] / f"{dive_number}.O2S.sampled.tsv",
        sensor_name="O2S",
        column_names=o2s_columns,
        drop_temperature=True
    )

    # -------------------------------------------------------------------
    # Merge for Hercules: CTD + Sealog + Herc_Depth + O2S
    # -------------------------------------------------------------------
    herc_merged = ctd_df.copy()
    for df in [sealog_df, herc_df, o2s_df]:
        if df is not None:
            df["Timestamp"] = pd.to_datetime(df["Timestamp"], utc=True, errors="coerce")
            herc_merged = herc_merged.merge(df, on="Timestamp", how="left")

    herc_merged, dupes_removed_herc = remove_timestamp_duplicates(herc_merged)
    if dupes_removed_herc > 0:
        print(f"Final check: Removed {dupes_removed_herc} duplicate timestamps from Hercules merged data")

    herc_merged["Timestamp"] = to_iso8601_str(herc_merged["Timestamp"])
    herc_output_path = dive_output_dir / f"{expedition}_{dive_number}_sealog_sensors_merged.csv"
    herc_merged.to_csv(herc_output_path, index=False, quoting=csv.QUOTE_ALL)
    print(f"Saved Hercules merged sensor data: {herc_output_path}")
    if report:
        report.add_output(herc_output_path, rows=len(herc_merged))
        if sealog_df is None:
            report.warn("missing-input",
                        f"dive {dive_number}: sealog export missing; merged file has no events")
        if herc_df is None:
            report.warn("missing-input",
                        f"dive {dive_number}: DEP1 depth file missing; merged file has no "
                        f"Herc_Depth_1 (the Kalman stage requires it)")
        if o2s_df is None:
            report.info("missing-input", f"dive {dive_number}: O2S file missing")

    # ---------------------------------------------------------
    # Load & Save ONLY raw Atalanta (DEP2) columns as-is
    # ---------------------------------------------------------
    # We expect the TSV columns: Timestamp, Lat, Long, Depth
    # => 4 columns total
    atalanta_df = load_tsv_file(
        paths["sampled_dir"] / f"{dive_number}.NAV.M2.sampled.tsv",
        column_names=["Lat", "Long", "Depth"],  # Raw columns from your TSV
        enforce_negative=False                  # Preserve raw values
    )

    if atalanta_df is not None:
        # Remove duplicates, then convert Timestamp to ISO8601 if desired
        atalanta_df, dupes_removed_at = remove_timestamp_duplicates(atalanta_df)
        if dupes_removed_at > 0:
            print(f"Removed {dupes_removed_at} duplicate timestamps from Atalanta data")

        atalanta_df["Timestamp"] = to_iso8601_str(atalanta_df["Timestamp"])

        # Save only these columns (Timestamp, Lat, Long, Depth) to CSV
        atalanta_output_path = dive_output_dir / f"{expedition}_{dive_number}_USBL_Atalanta.csv"
        atalanta_df.to_csv(atalanta_output_path, index=False, quoting=csv.QUOTE_ALL)
        print(f"Saved Atalanta sensor data: {atalanta_output_path}")
    else:
        print("No Atalanta data available for this dive.")

    final_rows_herc = len(herc_merged)
    print(f"Summary for dive {dive_number}:")
    print(f"  - Initial CTD rows: {initial_rows}")
    print(f"  - Final Hercules merged file rows: {final_rows_herc}")

# ------------------------------------------------------------------------------
# Function: process_data
# ------------------------------------------------------------------------------
def process_data(root_dir, *, output_dir=None, reports_dir=None):
    """
    Main processing function for dive sensor and Sealog data.

    This function processes only those dives that are listed in the dive summaries CSV
    (located at <root_dir>/RUMI_processed/all_dive_summaries.csv). It performs the following:
      1. Loads the dive summaries and extracts valid dive identifiers.
      2. Reads the dive reports directory to find dives matching those in the summaries.
      3. For each valid dive, it calls process_single_dive to merge the sensor datasets
         (for Hercules) and produce a separate CSV with raw Atalanta data.

    Parameters:
      root_dir (Path or str): The base directory for processing sensor data.
    """
    root_dir = Path(root_dir)
    output_dir = Path(output_dir) if output_dir else root_dir / "RUMI_processed"
    summary_path = output_dir / "all_dive_summaries.csv"
    print("Looking for dive summaries at:", summary_path.absolute())
    if not summary_path.exists():
        print("Dive summaries file not found. Cannot process sensor data.")
        return

    try:
        summary_df = pd.read_csv(summary_path)
        valid_dives = set(summary_df["dive"].astype(str).str.upper().str.strip())
        dive_reports_dir = Path(reports_dir) if reports_dir else root_dir / "processed" / "dive_reports"

        all_dives = [
            item.name.upper()
            for item in dive_reports_dir.iterdir()
            if item.is_dir() and item.name.upper().startswith("H")
        ]

        dive_list = [d for d in all_dives if d in valid_dives]
        if not dive_list:
            print("No valid dives found in dive summaries. Cannot process sensor data.")
            return
    except Exception as e:
        print(f"Error loading dive summaries: {e}")
        return

    report = RunReport("sensors_sealog", output_dir)
    for dive_num in dive_list:
        print(f"Processing dive {dive_num}...")
        rows = summary_df[summary_df["dive"].astype(str).str.upper().str.strip() == dive_num]
        expeditions = rows["expedition"].astype(str).str.strip().unique()
        if len(expeditions) != 1:
            raise ValueError(f"Ambiguous expedition for {dive_num}")
        process_single_dive(root_dir, expeditions[0], dive_num, report=report,
                            output_dir=output_dir, reports_dir=dive_reports_dir)
    report.finalize()

# ------------------------------------------------------------------------------
# Main Execution Block
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    root_directory = Path(input("Enter the base directory for processing: ").strip())
    process_data(root_directory)
