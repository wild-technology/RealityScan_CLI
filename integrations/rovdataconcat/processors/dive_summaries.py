from pathlib import Path
import csv
import pandas as pd
from datetime import timedelta

from .common import to_iso8601
from .report import RunReport

MIN_DIVE_HOURS = 2

RENAME_MAP = {
    "inwatertime": "Launch Time",
    "onbottomtime": "On Bottom Time",
    "offbottomtime": "Off Bottom Time",
    "ondecktime": "Recovery Time",
    "hercmaxdepth": "Herc Max Depth",
    "hercavgdepth": "Herc Avg Depth",
    "argusmaxdepth": "Atalanta Max Depth",
    "argusavgdepth": "Atalanta Avg Depth",
    "totaltime(hours)": "Total Time (hours)",
    "bottomtime(hours)": "Bottom Time (hours)",
}

TIME_FIELDS = ["Launch Time", "On Bottom Time", "Off Bottom Time", "Recovery Time", "Dive End"]


def extract_objective(summary_filepath):
    """Reads 'Objective:' line from summary file."""
    try:
        with summary_filepath.open("r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("Objective:"):
                    return line[len("Objective:"):].strip()
    except Exception as e:
        print(f"Error reading summary file {summary_filepath}: {e}")
    return ""


def read_tsv_with_commented_header(tsv_filepath):
    """
    Reads a TSV file whose first header line is commented (starts with '##').

    Validates that every data row has exactly as many fields as the header:
    a single stray tab (e.g. a trailing tab) would otherwise left-shift every
    column into valid-looking but WRONG values (dive windows from the wrong
    fields). Mismatches raise ValueError naming the file and row.
    """
    with tsv_filepath.open("r", encoding="utf-8") as f:
        header_line = f.readline().lstrip("#").strip()
        headers = header_line.split("\t")
        data_lines = f.read().splitlines()

    # The commented header's first column is the expedition identifier.
    headers[0] = "expedition"

    for lineno, line in enumerate(data_lines, start=2):
        if not line.strip():
            continue
        n_fields = len(line.split("\t"))
        if n_fields != len(headers):
            raise ValueError(
                f"{tsv_filepath.name} line {lineno}: {n_fields} fields but the "
                f"header declares {len(headers)} columns -- a stray tab would "
                f"silently shift every field into the wrong column. Fix the file."
            )

    return pd.read_csv(tsv_filepath, sep="\t", skiprows=1, header=None,
                       names=headers, index_col=False)


def process_dive_folder(dive_folder_path, dive_number):
    """Processes a single dive folder by reading stats and summary files."""
    # Nautilus exports tab-delimited statistics with either suffix. Inspect
    # content through the same strict parser; never silently prefer a duplicate.
    candidates = [dive_folder_path / f"{dive_number}-stats{suffix}"
                  for suffix in (".tsv", ".csv")]
    candidates = [path for path in candidates if path.is_file()]
    if len(candidates) > 1:
        if candidates[0].read_bytes() != candidates[1].read_bytes():
            raise ValueError(f"Conflicting statistics files for {dive_number}")
    stats_filepath = candidates[0] if candidates else dive_folder_path / f"{dive_number}-stats.tsv"
    summary_filepath = dive_folder_path / f"{dive_number}-summary.txt"

    if not stats_filepath.exists() or not summary_filepath.exists():
        print(f"Skipping {dive_number}: Missing required files.")
        return None

    try:
        df = read_tsv_with_commented_header(stats_filepath)
    except ValueError:
        # Malformed file structure (e.g. field-count mismatch): propagate so
        # the pipeline stops loudly instead of silently omitting the dive.
        raise
    except Exception as e:
        print(f"Error reading stats file {stats_filepath}: {e}")
        return None

    if "inwatertime" not in df.columns or "totaltime(hours)" not in df.columns:
        print(f"Skipping {dive_number}: Required columns missing.")
        return None

    # Rename raw columns first so each output name exists exactly once.
    df.rename(columns=RENAME_MAP, inplace=True)

    try:
        launch = pd.to_datetime(df["Launch Time"], utc=True, errors="coerce")
        total_hours = pd.to_numeric(df["Total Time (hours)"], errors="coerce")
        dive_end = launch + pd.to_timedelta(total_hours, unit="h")
    except Exception as e:
        print(f"Skipping {dive_number}: Error parsing timestamps: {e}")
        return None

    if pd.isnull(launch.iloc[0]) or pd.isnull(dive_end.iloc[0]):
        print(f"Skipping {dive_number}: Unparseable launch time or total time.")
        return None

    if (dive_end.iloc[0] - launch.iloc[0]) < timedelta(hours=MIN_DIVE_HOURS):
        print(f"Skipping {dive_number}: Dive too short (< {MIN_DIVE_HOURS} hours).")
        return None

    # Sanity-check event chronology: Launch < On Bottom < Off Bottom <
    # Recovery. Out-of-order times mean the columns are shifted or the file
    # is corrupt -- downstream dive windows would silently select the wrong
    # data, so this is an ERROR, not a warning.
    chronology = [("Launch Time", launch.iloc[0])]
    for field in ("On Bottom Time", "Off Bottom Time", "Recovery Time"):
        if field in df.columns:
            val = pd.to_datetime(df[field], utc=True, errors="coerce").iloc[0]
            if pd.notnull(val):
                chronology.append((field, val))
    for (prev_name, prev_val), (cur_name, cur_val) in zip(chronology, chronology[1:]):
        if not prev_val < cur_val:
            raise ValueError(
                f"{stats_filepath.name}: dive event times out of order -- "
                f"{prev_name} ({prev_val}) is not before {cur_name} ({cur_val}). "
                f"Expected Launch < On Bottom < Off Bottom < Recovery; the "
                f"stats row is corrupt or column-shifted."
            )

    # Dive End is derived (launch + total time); Recovery Time stays the
    # recorded on-deck time from the stats file.
    df["Dive End"] = to_iso8601(dive_end)
    df["Objective"] = extract_objective(summary_filepath)

    if "site" in df.columns:
        df["site"] = df["site"].astype(str).str.replace("_", " ")

    return df


def concatenate_dive_summaries(root_dir, *, output_dir=None, reports_dir=None, dive=None):
    """Processes all dive reports and saves a combined summary (timestamps without subseconds)."""
    root_dir = Path(root_dir)
    dive_reports_path = Path(reports_dir) if reports_dir else root_dir / "processed" / "dive_reports"

    if not dive_reports_path.exists():
        raise FileNotFoundError(f"Dive reports directory not found at {dive_reports_path}")

    processed_dir = Path(output_dir) if output_dir else root_dir / "RUMI_processed"
    report = RunReport("dive_summaries", processed_dir)

    combined_dfs = []
    skipped = []
    for item in sorted(dive_reports_path.iterdir()):
        if item.is_dir() and item.name.upper().startswith("H"):
            if dive and item.name.upper() != dive.upper():
                continue
            df = process_dive_folder(item, item.name.upper())
            if df is not None:
                combined_dfs.append(df)
            else:
                skipped.append(item.name.upper())

    report.metric("dives_included", len(combined_dfs))
    if skipped:
        report.warn("dives-skipped",
                    f"{len(skipped)} dive folders skipped (missing files, short dive, "
                    f"or bad timestamps): {', '.join(skipped)}")

    if not combined_dfs:
        print("No dive summaries were processed.")
        report.error("no-data", "no dive summaries could be processed")
        report.finalize()
        return

    all_dive_df = pd.concat(combined_dfs, ignore_index=True)

    if "expedition" not in all_dive_df.columns:
        print("Warning: 'expedition' column is missing! Check read_tsv_with_commented_header().")

    # Normalize all time columns to ISO8601 strings without subseconds.
    for field in TIME_FIELDS:
        if field in all_dive_df.columns:
            all_dive_df[field] = pd.to_datetime(
                all_dive_df[field], utc=True, errors="coerce"
            ).dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    processed_dir.mkdir(parents=True, exist_ok=True)
    summary_csv = processed_dir / "all_dive_summaries.csv"
    all_dive_df.to_csv(summary_csv, index=False, quoting=csv.QUOTE_ALL)

    print(f"\nCombined dive summaries saved to: {summary_csv}")
    report.add_output(summary_csv, rows=len(all_dive_df))
    report.finalize()


def process_data(root_dir, *, output_dir=None, reports_dir=None, dive=None):
    """Processes dive summaries from the raw data root directory."""
    root_dir = Path(root_dir)
    dive_reports_path = Path(reports_dir) if reports_dir else root_dir / "processed" / "dive_reports"

    if not dive_reports_path.exists():
        print(f"Error: Dive reports directory not found at {dive_reports_path}")
        return

    print(f"Processing dive summaries from {dive_reports_path}...")
    concatenate_dive_summaries(root_dir, output_dir=output_dir,
                              reports_dir=dive_reports_path, dive=dive)
