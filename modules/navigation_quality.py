"""Vehicle navigation validation and explicit per-image temporal coverage."""
from __future__ import annotations

import argparse
import csv
import json
from numbers import Real
from pathlib import Path
import re

import numpy as np
import pandas as pd
from pyproj import Transformer

from .source_inventory import SourceItem, file_hash

POSE_COLUMNS = ("kalman_x", "kalman_y", "kalman_depth", "kalman_yaw_deg",
                "kalman_pitch_deg", "kalman_roll_deg", "kalman_lat", "kalman_long")


def load_navigation(path: Path, expedition: str, dive: str) -> pd.DataFrame:
    path = Path(path)
    if path.stem != f"{expedition}_{dive}_final_datatable" or path.suffix.lower() not in ('.csv', '.tsv'):
        raise ValueError("Navigation filename must identify this expedition/dive and vehicle output")
    before = file_hash(path)
    with path.open(encoding='utf-8-sig', newline='') as stream:
        header = stream.readline()
    # Select delimiter from the header columns, not the filename extension.
    delimiters = [sep for sep in (',', '\t', ';')
                  if 'Timestamp' in next(csv.reader([header], delimiter=sep))]
    if len(delimiters) != 1:
        raise ValueError('Navigation delimiter/header is ambiguous or missing Timestamp')
    frame = pd.read_csv(path, sep=delimiters[0], low_memory=False, encoding='utf-8-sig')
    if file_hash(path) != before:
        raise ValueError('Navigation changed while loading')
    required = {"Timestamp", "utm_zone", *POSE_COLUMNS}
    if missing := required - set(frame.columns):
        raise ValueError(f"Missing navigation columns: {sorted(missing)}")
    if frame.empty:
        raise ValueError("Navigation has no rows")
    # Generated tables explicitly mark UTC. Naive input is refused here rather
    # than interpreted using the workstation's timezone.
    if not frame["Timestamp"].astype(str).str.endswith("Z").all():
        raise ValueError("Navigation timestamps must explicitly declare UTC (Z)")
    frame["Timestamp"] = pd.to_datetime(frame["Timestamp"], utc=True, errors="raise")
    if frame['Timestamp'].isna().any() or frame["Timestamp"].duplicated().any() or not frame["Timestamp"].is_monotonic_increasing:
        raise ValueError("Navigation timestamps must be unique and ordered")
    for column in POSE_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    labels = frame["utm_zone"].astype(str).unique()
    if len(labels) != 1 or not re.fullmatch(r"(?:[1-9]|[1-5][0-9]|60)[NS]", labels[0]):
        raise ValueError("Navigation must declare exactly one valid UTM zone/hemisphere")
    frame.attrs['source_sha256'] = before
    frame.attrs['source_path'] = str(path.resolve())
    return frame


def assess_navigation(path: Path, expedition: str, dive: str) -> dict:
    frame = load_navigation(path, expedition, dive)
    values = frame[list(POSE_COLUMNS)].to_numpy(dtype=np.float64)
    finite = np.isfinite(values).all(axis=1)
    zone = str(frame["utm_zone"].iloc[0])
    epsg = (32600 if zone[-1] == "N" else 32700) + int(zone[:-1])
    tx = Transformer.from_crs(4326, epsg, always_xy=True)
    east, north = tx.transform(frame["kalman_long"].to_numpy(), frame["kalman_lat"].to_numpy())
    projection_error = np.hypot(east - frame["kalman_x"], north - frame["kalman_y"])
    gaps = frame["Timestamp"].diff().dt.total_seconds()
    errors = []
    if not finite.all():
        errors.append(f"{int((~finite).sum())} rows have incomplete/nonfinite poses")
    if (frame["kalman_depth"] > 0).any():
        errors.append("Positive depth in negative-down vehicle navigation")
    if not frame["kalman_lat"].between(-80, 84).all() or not frame["kalman_long"].between(-180, 180).all():
        errors.append("Coordinates outside valid UTM geographic domain")
    if not np.isfinite(projection_error).all() or projection_error.max() > 0.001:
        errors.append("Lat/lon and UTM output disagree by more than 1 mm")
    summary = {"schema_version": 1, "path": str(Path(path).resolve()),
               "sha256": frame.attrs['source_sha256'], "expedition": expedition, "dive": dive,
               "rows": len(frame), "utm_zone": zone, "epsg": epsg,
               "start_utc": frame["Timestamp"].iloc[0].isoformat(),
               "end_utc": frame["Timestamp"].iloc[-1].isoformat(),
               "finite_pose_rows": int(finite.sum()), "max_gap_s": float(gaps.max()) if len(frame) > 1 else 0.0,
               "gaps_over_2s": int((gaps > 2).sum()),
               "depth_min_m": _finite_or_none(frame["kalman_depth"].min()),
               "depth_max_m": _finite_or_none(frame["kalman_depth"].max()),
               "projection_max_error_m": _finite_or_none(projection_error.max()),
               "errors": errors, "structurally_valid": not errors,
               "limitations": ["This check does not establish absolute navigation accuracy",
                                "Pressure-depth vertical datum requires a stated project assumption",
                                "Camera clocks and mount geometry require project approval"]}
    if file_hash(Path(path)) != frame.attrs['source_sha256']:
        raise ValueError('Navigation changed during assessment')
    return summary


def _finite_or_none(value):
    return float(value) if np.isfinite(value) else None


def match_images(items: list[SourceItem], frame: pd.DataFrame, max_delta_s: float = 2, *,
                 include_excluded: bool = False, include_duplicates: bool = False,
                 clock_offset_seconds: float = 0, cancelled=None, progress=None) -> dict:
    """Match at image UTC + clock offset, applied once without changing inventory.

    Positive offsets move the matching target later. The finite offset is bounded
    to +/-86400 seconds; range/tolerance checks use the adjusted target. Original
    timestamps and content approval tokens remain unchanged. Never extrapolate.
    """
    if isinstance(clock_offset_seconds, (bool, np.bool_)) or not isinstance(clock_offset_seconds, Real):
        raise ValueError("Clock offset must be a finite number within +/-86400 seconds")
    if not -86400 <= clock_offset_seconds <= 86400:
        raise ValueError("Clock offset must be a finite number within +/-86400 seconds")
    clock_offset_seconds = float(clock_offset_seconds)
    offset = pd.Timedelta(seconds=clock_offset_seconds)
    if not np.isfinite(max_delta_s) or max_delta_s < 0:
        raise ValueError("Maximum match delta must be finite and nonnegative")
    # pandas 3 may preserve microseconds. Timestamp.value is nanoseconds, so
    # normalize the array's unit explicitly before comparing integers.
    if frame.empty or {'Timestamp', *POSE_COLUMNS} - set(frame.columns):
        raise ValueError('Navigation frame must be nonempty and contain timestamp/pose columns')
    stamps = frame['Timestamp']
    if (not isinstance(stamps.dtype, pd.DatetimeTZDtype) or stamps.isna().any()
            or stamps.duplicated().any() or not stamps.is_monotonic_increasing):
        raise ValueError('Navigation times must be timezone-aware, valid, unique and ordered')
    times = stamps.dt.as_unit("ns").astype("int64").to_numpy()
    pose_finite = np.isfinite(frame[list(POSE_COLUMNS)].apply(pd.to_numeric, errors='coerce')
                             .to_numpy(dtype=float)).all(axis=1)
    matched, unmatched = [], []
    total = len(items)
    for item_number, item in enumerate(items, 1):
        if cancelled is not None and cancelled():
            raise InterruptedError('Navigation matching cancelled')
        if progress is not None and (item_number % 1000 == 0 or item_number == total):
            progress(item_number, total, item.path)
        if (item.kind != "image" or (not item.included and not include_excluded)
                or (item.duplicate_of and not include_duplicates)):
            continue
        record = {"path": item.path, "camera": item.camera, "timestamp_utc": item.timestamp_utc}
        try:
            target = pd.Timestamp(item.timestamp_utc)
            if pd.isna(target) or target.tzinfo is None:
                raise ValueError("Missing/invalid timestamp or timezone")
            target = target + offset
            record["match_timestamp_utc"] = target.tz_convert("UTC").isoformat()
            stamp = target.value
            at = int(np.searchsorted(times, stamp))
            candidates = [i for i in (at - 1, at) if 0 <= i < len(times)]
            index = min(candidates, key=lambda i: (abs(int(times[i]) - stamp), i))
            delta = abs(int(times[index]) - stamp) / 1e9
            record.update(nav_row=index, delta_s=delta)
            if stamp < times[0] or stamp > times[-1]:
                raise ValueError("Image outside navigation time range; extrapolation refused")
            if delta > max_delta_s:
                raise ValueError(f"Nearest navigation is {delta:.3f} s away")
            if not pose_finite[index]:
                raise ValueError("Nearest navigation row lacks a complete finite pose")
            matched.append(record)
        except (ValueError, TypeError, OverflowError) as exc:
            record["exception"] = str(exc)
            unmatched.append(record)
    return {"matched_count": len(matched), "unmatched_count": len(unmatched),
            "clock_offset_seconds": clock_offset_seconds,
            "max_delta_s": max_delta_s, "matched": matched, "unmatched": unmatched}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("navigation", type=Path)
    parser.add_argument("--expedition", required=True)
    parser.add_argument("--dive", required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    result = assess_navigation(args.navigation, args.expedition, args.dive)
    payload = json.dumps(result, indent=2, allow_nan=False)
    print(payload)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x", encoding="utf-8") as handle:
            handle.write(payload)
    return 0 if result["structurally_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
