from pathlib import Path
import math
import re
import pandas as pd
from datetime import datetime, timedelta, timezone

from .common import best_fix_per_second, drop_duplicate_timestamps
from .report import RunReport

PARSER_VERSION = "sdyn-utc-integrity-1"
MAX_PREFIX_SKEW_SECONDS = 60.0
# Known acoustic/legacy fix codes. This is an explicit acceptance policy, not
# an assertion that proprietary Sonardyne quality codes equal GNSS accuracy.
VALID_FIX_QUALITIES = frozenset({1, 2})
COLUMNS = ["Timestamp", "Latitude", "Longitude", "Accuracy", "Depth", "Vehicle"]


class SdynRejected(ValueError):
    """A rejected observation with a stable machine-readable reason."""


def filename_start(filepath):
    """Date fallback for bare legacy GGA only; a prefix never falls back."""
    try:
        return datetime.strptime(Path(filepath).stem, "%Y%m%d_%H%M").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_sdyn_line(line, *, file_start=None, max_prefix_skew_s=MAX_PREFIX_SKEW_SECONDS):
    """Return (record, time_basis), or reject with a stable reason.

    Prefixed records retain GGA acquisition time on the closest adjacent UTC date
    to receipt. A <=60 s default disagreement bound is an engineering integrity
    policy, not latency calibration. Legacy bare sentences preserve the existing
    filename/minute rollover behavior. Metadata is separate from CSV columns.
    """
    if not math.isfinite(max_prefix_skew_s) or max_prefix_skew_s < 0:
        raise ValueError("max_prefix_skew_s must be finite and nonnegative")
    text = line.strip()
    if not text:
        raise SdynRejected("empty_line")
    receipt = None
    if text.startswith("$GPGGA,"):
        sentence = text
    else:
        prefix = re.fullmatch(r"SDYN\s+(\S+)\s+SONARDYNE\s+(\$GPGGA,.*)", text)
        if not prefix:
            raise SdynRejected("invalid_prefix" if text.startswith("SDYN") else "unsupported_record")
        timestamp, sentence = prefix.groups()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", timestamp):
            raise SdynRejected("invalid_prefix_utc")
        try:
            receipt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            raise SdynRejected("invalid_prefix_utc") from None
    if "*" not in sentence:
        raise SdynRejected("missing_checksum")
    match = re.fullmatch(r"\$([^*]+)\*([0-9A-Fa-f]{2})", sentence)
    if not match:
        raise SdynRejected("malformed_checksum")
    body, supplied = match.groups()
    try:
        encoded = body.encode("ascii")
    except UnicodeEncodeError:
        raise SdynRejected("non_ascii_sentence") from None
    checksum = 0
    for byte in encoded:
        checksum ^= byte
    if checksum != int(supplied, 16):
        raise SdynRejected("checksum_mismatch")
    fields = body.split(",")
    if len(fields) != 15 or fields[0] != "GPGGA":
        raise SdynRejected("invalid_fields")
    (_, clock, latitude, ns, longitude, ew, quality, satellites,
     accuracy, depth, depth_unit, geoid, geoid_unit, age, beacon) = fields
    if not re.fullmatch(r"\d{1,6}(?:\.\d{1,6})?", clock):
        raise SdynRejected("invalid_fix_time")
    integer, _, fraction = clock.partition(".")
    clock = integer.zfill(6) + ("." + fraction if fraction else "")
    try:
        fix_time = datetime.strptime(clock, "%H%M%S.%f" if fraction else "%H%M%S")
    except ValueError:
        raise SdynRejected("invalid_fix_time") from None
    if receipt is not None:
        same_day = receipt.replace(hour=fix_time.hour, minute=fix_time.minute,
                                   second=fix_time.second, microsecond=fix_time.microsecond)
        choices = [same_day]
        for offset in (-1, 1):
            try:
                choices.append(same_day + timedelta(days=offset))
            except OverflowError:
                pass  # Calendar boundary; same-day candidate still exists.
        timestamp = min(choices, key=lambda dt: (abs((dt - receipt).total_seconds()), dt))
        if abs((timestamp - receipt).total_seconds()) > max_prefix_skew_s:
            raise SdynRejected("prefix_fix_time_disagreement")
        basis = "prefix_utc"
    else:
        if file_start is None:
            raise SdynRejected("missing_legacy_date")
        timestamp = file_start.replace(hour=fix_time.hour, minute=fix_time.minute,
                                       second=fix_time.second, microsecond=fix_time.microsecond)
        if timestamp < file_start - timedelta(hours=1):
            timestamp += timedelta(days=1)
        basis = "legacy_filename"
    quality_code = quality.lstrip('0') or '0'
    if not quality.isdigit() or quality_code not in {str(code) for code in VALID_FIX_QUALITIES}:
        raise SdynRejected("invalid_fix_quality" if quality_code == "0" else "unsupported_fix_quality")
    if not satellites.isdigit() or not re.fullmatch(r"\d{4}", beacon):
        raise SdynRejected("invalid_fields")
    if ns not in ("N", "S") or ew not in ("E", "W"):
        raise SdynRejected("invalid_hemisphere")
    if not re.fullmatch(r"\d{4}(?:\.\d+)?", latitude) or not re.fullmatch(r"\d{5}(?:\.\d+)?", longitude):
        raise SdynRejected("invalid_coordinate_format")
    lat_degrees, lat_minutes = int(latitude[:2]), float(latitude[2:])
    lon_degrees, lon_minutes = int(longitude[:3]), float(longitude[3:])
    if (lat_minutes >= 60 or lon_minutes >= 60 or lat_degrees > 90 or lon_degrees > 180
            or (lat_degrees == 90 and lat_minutes != 0)
            or (lon_degrees == 180 and lon_minutes != 0)):
        raise SdynRejected("coordinate_out_of_range")
    try:
        accuracy_value, depth_value = float(accuracy), float(depth)
        unused = [float(geoid), float(age)]
    except ValueError:
        raise SdynRejected("invalid_numeric_field") from None
    if not all(math.isfinite(v) for v in [accuracy_value, depth_value, *unused]):
        raise SdynRejected("nonfinite_numeric_field")
    if accuracy_value <= 0:
        raise SdynRejected("nonpositive_accuracy")
    if depth_unit != "M" or geoid_unit != "M" or any(v != 0 for v in unused):
        raise SdynRejected("unsupported_sdyn_layout")
    if int(beacon) != 1:
        raise SdynRejected("excluded_atalanta" if int(beacon) == 2 else "unsupported_beacon")
    lat = (lat_degrees + lat_minutes / 60) * (-1 if ns == "S" else 1)
    lon = (lon_degrees + lon_minutes / 60) * (-1 if ew == "W" else 1)
    return dict(zip(COLUMNS, [timestamp, lat, lon, accuracy_value, depth_value, "Hercules"])), basis


def parse_sdyn_file(filepath, *, stats=None):
    """Read without mutation; reject invalid observations and account for every line.

    Stats retain totals/reasons and at most five source line examples per reason.
    Accuracy interpretation is unchanged; its physical units/confidence still
    require a deployed-format contract. Only Hercules records reach the table.
    """
    filepath = Path(filepath)
    stats = stats if stats is not None else {}
    reasons = stats.setdefault("reasons", {})
    examples = stats.setdefault("examples", {})
    data = []
    file_start = filename_start(filepath)
    with filepath.open("r", encoding="utf-8", errors="replace") as stream:
        for number, line in enumerate(stream, 1):
            stats["lines_seen"] = stats.get("lines_seen", 0) + 1
            try:
                record, basis = parse_sdyn_line(line, file_start=file_start)
            except SdynRejected as exc:
                reason = str(exc)
                reasons[reason] = reasons.get(reason, 0) + 1
                if len(examples.setdefault(reason, [])) < 5:
                    examples[reason].append({"file": str(filepath), "line": number})
                continue
            stats["accepted"] = stats.get("accepted", 0) + 1
            stats[basis] = stats.get(basis, 0) + 1
            data.append(record)
    return pd.DataFrame(data, columns=COLUMNS)

def process_all_sdyn_files(root_directory, *, files=None, stats=None):
    """
    Processes all SDYN files found in <root_directory>/raw/datalog.

    Parameters:
        root_directory (Path or str): The base directory containing the raw data.

    Returns:
        pandas.DataFrame: Combined DataFrame containing data from all SDYN files.
    """
    root_directory = Path(root_directory)
    sdyn_dir = root_directory / "raw" / "datalog"

    if not sdyn_dir.exists():
        raise FileNotFoundError(f"SDYN directory not found at {sdyn_dir}")

    # Find all .SDYN files regardless of extension case. Windows globbing is
    # case-insensitive, so concatenating two glob lists double-counted every
    # file; a set union dedupes there while still catching both spellings on
    # case-sensitive filesystems. Sorted for deterministic processing order.
    files = (sorted(set(files)) if files is not None else
             sorted(set(sdyn_dir.glob("*.SDYN")) | set(sdyn_dir.glob("*.sdyn"))))

    dataframes = []
    for filepath in files:
        df = parse_sdyn_file(filepath, stats=stats)
        if not df.empty:
            dataframes.append(df)

    if dataframes:
        return pd.concat(dataframes, ignore_index=True)
    else:
        return pd.DataFrame()

def process_dive_vehicle(dive_summary, sdyn_data):
    """
    Filters and processes SDYN data for a given dive.

    Uses the dive summary (which must contain 'dive', 'Launch Time', and 'Recovery Time')
    to filter the USBL fixes in sdyn_data to those within the dive's time window.
    For each vehicle (other than "Unknown"), duplicate fixes are culled.

    Parameters:
        dive_summary (pandas.Series): A row from the dive summaries DataFrame.
        sdyn_data (pandas.DataFrame): DataFrame containing parsed SDYN data.

    Returns:
        dict: A dictionary with keys as vehicle names and values as DataFrames of processed fixes.
    """
    dive_id = str(dive_summary["dive"]).strip()
    launch_time = dive_summary["Launch Time"]
    recovery_time = dive_summary["Recovery Time"]

    sdyn_data["Timestamp"] = pd.to_datetime(sdyn_data["Timestamp"], utc=True)
    df_dive = sdyn_data[(sdyn_data["Timestamp"] >= launch_time) & (sdyn_data["Timestamp"] <= recovery_time)]
    if df_dive.empty:
        print(f"No USBL fixes for dive {dive_id}.")
        return {}

    processed = {}
    for vehicle in df_dive["Vehicle"].unique():
        if vehicle == "Unknown":
            continue
        df_vehicle = df_dive[df_dive["Vehicle"] == vehicle].copy()
        # Keep the best-accuracy fix per second; result is chronologically sorted.
        df_vehicle, orig, final = best_fix_per_second(df_vehicle, quality_col="Accuracy")
        if orig != final:
            print(f"Reduced {orig} fixes to {final} (best accuracy per second) "
                  f"for dive {dive_id}, vehicle {vehicle}")

        processed[vehicle] = df_vehicle

    return processed

def process_data(root_directory, *, output_dir=None, files=None):
    """
    Main processing function for USBL data.

    Reads dive summaries from <root_directory>/RUMI_processed/all_dive_summaries.csv,
    processes SDYN files from <root_directory>/raw/datalog,
    and for each dive, filters USBL fixes within the dive's time window,
    applies duplicate culling based on best accuracy, and saves processed data as CSV files.

    Processed CSV files are saved under <root_directory>/RUMI_processed/<dive_id>/,
    with filenames formatted as: <expedition>_<dive_id>_USBL_<vehicle>.csv.

    Parameters:
        root_directory (Path or str): The base directory containing raw data and processed data.
    """
    root_directory = Path(root_directory)
    processed_dir = Path(output_dir) if output_dir else root_directory / "RUMI_processed"
    summary_path = processed_dir / "all_dive_summaries.csv"

    if not summary_path.exists():
        print(f"Error: Dive summary file not found at {summary_path}")
        return

    try:
        dive_summaries = pd.read_csv(summary_path)
        dive_summaries["Launch Time"] = pd.to_datetime(dive_summaries["Launch Time"], utc=True, errors="coerce")
        dive_summaries["Recovery Time"] = pd.to_datetime(dive_summaries["Recovery Time"], utc=True, errors="coerce")
    except Exception as e:
        print(f"Error reading dive summaries from {summary_path}: {e}")
        return

    report = RunReport("usbl_sdyn", processed_dir)
    stats = {}
    try:
        input_files = (list(files) if files is not None else
                       sorted(p for p in (root_directory / 'raw/datalog').iterdir()
                              if p.is_file() and p.suffix.lower() == '.sdyn'))
        for path in input_files:
            report.add_input(path)
        sdyn_data = process_all_sdyn_files(root_directory, files=input_files, stats=stats)
    except Exception as e:
        print(f"Error processing SDYN files: {e}")
        report.error("read-failed", str(e))
        report.metric("parse_accounting", stats)
        report.finalize()
        return

    report.metric("parser_version", PARSER_VERSION)
    report.metric("prefix_max_skew_seconds", MAX_PREFIX_SKEW_SECONDS)
    report.metric("accepted_quality_codes", sorted(VALID_FIX_QUALITIES))
    report.metric("parse_accounting", stats)
    for reason, count in sorted(stats.get("reasons", {}).items()):
        if reason in ("excluded_atalanta", "empty_line"):
            report.info(reason, f"{count} observations excluded")
        else:
            report.warn(reason, f"{count} observations rejected; see parse_accounting examples")
    report.metric("raw_fixes_parsed", len(sdyn_data))

    if sdyn_data.empty:
        print("No USBL fixes found.")
        report.error("no-data", "no USBL fixes parsed from any SDYN file")
        report.finalize()
        return

    # Process each dive and save output files
    for _, dive_row in dive_summaries.iterrows():
        dive_id = str(dive_row["dive"]).strip()
        expedition = str(dive_row.get("expedition", "NA")).strip()
        processed = process_dive_vehicle(dive_row, sdyn_data)
        if processed:
            dive_out_dir = processed_dir / dive_id
            dive_out_dir.mkdir(parents=True, exist_ok=True)

            for vehicle, df_vehicle in processed.items():
                # Final safety net: drop any duplicate timestamps, keep chronological order.
                df_final, final_dupes_removed = drop_duplicate_timestamps(df_vehicle)
                if final_dupes_removed > 0:
                    print(
                        f"Removed {final_dupes_removed} final duplicate timestamps for dive {dive_id}, vehicle {vehicle}")

                fname = f"{expedition}_{dive_id}_USBL_{vehicle}.csv"
                outpath = dive_out_dir / fname
                try:
                    df_final.to_csv(outpath, index=False)
                    print(f"Saved processed data for dive {dive_id}, vehicle {vehicle} to: {outpath}")
                    report.add_output(outpath, rows=len(df_final))
                except Exception as e:
                    print(f"Error saving file {outpath}: {e}")
                    report.error("write-failed", f"could not write {outpath}: {e}")
        else:
            print(f"No valid data to process for dive {dive_id}.")
            report.warn("no-data", f"dive {dive_id}: no USBL fixes in the dive window")

    report.finalize()
