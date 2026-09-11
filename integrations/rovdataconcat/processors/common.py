"""
Shared helpers for the ROV data pipeline.

Centralizes behavior that was previously duplicated (with drift) across
processor modules:

* ISO8601 timestamp formatting ("YYYY-MM-DDTHH:MM:SSZ", UTC, no subseconds)
* Second-alignment of high-rate fixes (round to *nearest* second everywhere)
* Duplicate-timestamp removal (always returns chronologically sorted data)
* Deriving <expedition>/<dive> identifiers from the processed directory
"""

from pathlib import Path
import math

import pandas as pd

ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"


def to_iso8601(dt_series: pd.Series) -> pd.Series:
    """Format a datetime Series as ISO8601 UTC strings without subseconds."""
    return dt_series.apply(
        lambda dt: dt.strftime(ISO_FMT) if pd.notnull(dt) else dt
    )


def drop_duplicate_timestamps(df: pd.DataFrame, sort_by: str = "Timestamp"):
    """
    Drop rows with duplicate timestamps (keep first) and return the frame
    sorted chronologically.

    Returns (df, removed_count).
    """
    if df is None or df.empty:
        return df, 0
    before = len(df)
    out = df.drop_duplicates(subset=["Timestamp"]).sort_values(sort_by, kind="mergesort")
    return out, before - len(out)


def best_fix_per_second(df: pd.DataFrame, quality_col: str = None):
    """
    Align fixes to whole seconds by rounding Timestamp to the nearest second,
    then keep one row per second:

    * quality_col given  -> row with the lowest value in that column
      (e.g. USBL 'Accuracy'),
    * otherwise          -> the fix whose original time is closest to the
      rounded second.

    The Timestamp column of the result is an ISO8601 string. The result is
    sorted chronologically. Returns (df, original_count, final_count).
    """
    if df.empty:
        return df.copy(), 0, 0

    orig = len(df)
    # idxmin/loc select labels, not row positions: repeated input indices must
    # not allow a worse fix to replace the winner from another second.
    work = df.reset_index(drop=True).copy()
    # Coerce to datetime64 UTC in case the column arrived as python datetime
    # objects (object dtype) or strings; drop rows that cannot be parsed.
    ts = pd.to_datetime(work["Timestamp"], utc=True, errors="coerce")
    n_bad = int(ts.isna().sum())
    if n_bad:
        print(f"  - Dropping {n_bad} rows with unparseable timestamps")
        work = work[ts.notna()]
        ts = ts[ts.notna()]
    if work.empty:
        return work.reset_index(drop=True), orig, 0
    work["Timestamp"] = ts
    work["_rounded"] = ts.dt.round("s")

    if quality_col is not None:
        # NaN quality must not win a group, and all-NaN groups must not crash
        # idxmin -- treat missing quality as worst possible.
        work["_q"] = work[quality_col].fillna(float("inf"))
        keep_idx = work.groupby("_rounded")["_q"].idxmin()
        # For two source seconds that round to the same target second, keep the
        # better-quality row (deterministic via stable sort below).
        collision_sort = ["_rounded", "_q"]
    else:
        work["_diff"] = (work["Timestamp"] - work["_rounded"]).abs()
        keep_idx = work.groupby("_rounded")["_diff"].idxmin()
        collision_sort = ["_rounded", "_diff"]

    out = work.loc[keep_idx].copy()
    out.sort_values(collision_sort, kind="mergesort", inplace=True)
    out["Timestamp"] = out["_rounded"].dt.strftime(ISO_FMT)
    out.drop(columns=[c for c in ("_rounded", "_diff", "_q") if c in out.columns],
             inplace=True)
    # Rounding can map two source seconds onto one target second; the sort
    # above puts the better candidate first.
    out = out.drop_duplicates(subset=["Timestamp"])
    out.sort_values("Timestamp", kind="mergesort", inplace=True)
    out.reset_index(drop=True, inplace=True)
    return out, orig, len(out)


def find_time_gaps(ts_series, max_gap_s=60):
    """
    Find gaps larger than max_gap_s seconds in a timestamp series.

    Returns a list of (gap_start_iso, gap_end_iso, gap_seconds), largest first.
    """
    ts = pd.to_datetime(ts_series, utc=True, errors="coerce").dropna().sort_values()
    if len(ts) < 2:
        return []
    diffs = ts.diff().dt.total_seconds()
    gaps = []
    for pos in range(1, len(ts)):
        g = diffs.iloc[pos]
        if g > max_gap_s:
            gaps.append((
                ts.iloc[pos - 1].strftime(ISO_FMT),
                ts.iloc[pos].strftime(ISO_FMT),
                float(g),
            ))
    gaps.sort(key=lambda x: -x[2])
    return gaps


def determine_utm_zone(lon, lat):
    """Determine the UTM zone (number, hemisphere) for a lon/lat coordinate."""
    if not (math.isfinite(lon) and math.isfinite(lat)
            and -180 <= lon <= 180 and -80 <= lat <= 84):
        raise ValueError(f"Coordinate outside the UTM domain: {lon}, {lat}")
    zone_number = min(60, int((lon + 180) / 6) + 1)

    # Special cases for Norway and Svalbard
    if 56.0 <= lat < 64.0 and 3.0 <= lon < 12.0:
        zone_number = 32
    if 72.0 <= lat < 84.0:
        if 0.0 <= lon < 9.0:
            zone_number = 31
        elif 9.0 <= lon < 21.0:
            zone_number = 33
        elif 21.0 <= lon < 33.0:
            zone_number = 35
        elif 33.0 <= lon < 42.0:
            zone_number = 37

    hemisphere = "north" if lat >= 0 else "south"
    return zone_number, hemisphere


def utm_proj_string(lon, lat):
    """proj4 string for the WGS84 UTM zone containing lon/lat."""
    zone_number, hemisphere = determine_utm_zone(lon, lat)
    return f"+proj=utm +zone={zone_number} +{hemisphere} +datum=WGS84 +units=m +no_defs"


def proj_string_for_zone_label(zone_label):
    """
    proj4 string for a UTM zone label like '53N' or '4S' (the format
    kalman_filter records in the final datatable's utm_zone column).
    """
    label = str(zone_label).strip().upper()
    if not label or label[-1] not in ("N", "S") or not label[:-1].isdigit():
        raise ValueError(f"Invalid UTM zone label '{zone_label}' (expected e.g. '53N')")
    zone_number = int(label[:-1])
    if not 1 <= zone_number <= 60:
        raise ValueError(f"UTM zone number {zone_number} is out of range 1-60")
    hemisphere = "north" if label[-1] == "N" else "south"
    return f"+proj=utm +zone={zone_number} +{hemisphere} +datum=WGS84 +units=m +no_defs"


def expedition_dive_from_processed_dir(processed_dir: Path):
    """
    Derive (expedition, dive) from the standardized layout
    <base>/<EXPEDITION>/RUMI_processed/<DIVE>.
    """
    processed_dir = Path(processed_dir).resolve()
    dive = processed_dir.name
    expedition = processed_dir.parent.parent.name
    if processed_dir.parent.name != "RUMI_processed" or not expedition:
        print(f"Warning: '{processed_dir}' does not match the expected layout "
              f"<base>/<EXPEDITION>/RUMI_processed/<DIVE>; derived "
              f"expedition='{expedition}', dive='{dive}'. File names may be wrong.")
    return expedition, dive
