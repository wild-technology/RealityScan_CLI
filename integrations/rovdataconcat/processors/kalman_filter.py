#!/usr/bin/env python3
"""
kalman_filter.py

Applies a Kalman Filter to the merged ROV data, preserving ISO8601 timestamps
(e.g., "2023-11-01T19:00:01Z") in the final CSV.

This version handles heading data separately from the main Kalman filter
to properly account for the circular nature of angular data.

Intended to be executed via the data processing orchestrator which passes the
raw and processed directories (including dive folder information).
"""

from pathlib import Path
import os
import sys
import traceback
import csv
import math
import numpy as np
import pandas as pd
from filterpy.kalman import KalmanFilter
from pyproj import Proj
from scipy.ndimage import gaussian_filter1d

from .common import expedition_dive_from_processed_dir, determine_utm_zone, utm_proj_string
from .report import RunReport

# Reject a DVL position fix sitting further than this from the current state
# estimate. The gate has to clear LEGITIMATE USBL-vs-DVL disagreement while
# still catching a stale dead-reckoning anchor.
#
# Sizing, from H2060's own numbers: consecutive DVL steps are sub-metre
# (p99 0.4 m), but the two sources genuinely disagree by ~256 m at the start
# of the dive before the filter converges - a first cut at 250 m rejected
# those valid fixes, which the regression test caught. 1 km is ~4x that
# observed disagreement and still rejects H2060's 250 km stale anchor by a
# factor of 250, so there is a wide margin on both sides.
#
# Raising this is safe-ish; lowering it toward the few-hundred-metre mark
# starts discarding real DVL and risks reinstating the "DVL never used" bug.
DVL_INNOVATION_GATE_M = 1000.0


def deg2rad(deg):
    """Safely convert degrees to radians, handling NaNs."""
    try:
        return np.deg2rad(float(deg))
    except (ValueError, TypeError):
        return np.nan


def rad2deg_scalar(rad):
    """Safely convert radians to degrees, handling NaNs."""
    try:
        return np.rad2deg(float(rad))
    except (ValueError, TypeError):
        return np.nan


def wrap_angle(angle):
    """Ensure angles remain within [-pi, pi)."""
    return (angle + np.pi) % (2 * np.pi) - np.pi


def filter_heading(headings, window_size=11):
    """
    Filter heading data using a specialized approach for circular quantities.
    Uses a Gaussian-weighted window to properly handle angle wrapping.

    Args:
        headings: Array of heading values in degrees.
        window_size: Size of the filtering window (odd number recommended).

    Returns:
        Array of filtered heading values in degrees [0, 360).
    """
    if len(headings) == 0 or np.all(np.isnan(headings)):
        return np.full_like(headings, np.nan)

    # Convert to radians and then to sine and cosine components
    rad = np.deg2rad(headings)
    sin_vals = np.sin(rad)
    cos_vals = np.cos(rad)

    # Interpolate NaN values
    valid_mask = ~np.isnan(headings)
    if np.any(~valid_mask):
        sin_vals = np.interp(np.arange(len(sin_vals)), np.where(valid_mask)[0], sin_vals[valid_mask])
        cos_vals = np.interp(np.arange(len(cos_vals)), np.where(valid_mask)[0], cos_vals[valid_mask])

    # Apply Gaussian smoothing
    sigma = max(window_size / 5.0, 1.0)
    sin_smooth = gaussian_filter1d(sin_vals, sigma, mode='nearest')
    cos_smooth = gaussian_filter1d(cos_vals, sigma, mode='nearest')

    # Convert back to degrees in [0, 360)
    filtered_rad = np.arctan2(sin_smooth, cos_smooth)
    filtered_deg = np.mod(np.rad2deg(filtered_rad), 360)
    return filtered_deg


# NOTE (merge of 169ca4a and fe2242c): both sides independently replaced
# per-source zone derivation with ONE pinned dive projection. 169ca4a's
# pin_utm_projection (median fix, robust to a bad leading row) supersedes
# fe2242c's derive_shared_utm (first valid fix); fe2242c's contribution --
# persisting the pinned zone as a utm_zone column that kalman_offset
# verifies against -- is layered on in process_data below.
def pin_utm_projection(df, sources):
    """ONE UTM projection for every position source in this dive.

    Returns (Proj, zone_number, hemisphere, lat, lon) or (None, ...) when no
    source has a usable fix.

    WHY THIS EXISTS (NA165 H2060, 2026-08-14): each source used to derive
    its OWN projection from its OWN first valid row, and the filter then
    fused the resulting eastings as if they shared a frame. On H2060 the
    DVL's first row is a 250 km outlier at lon -167.99, which pinned DVL to
    zone 3, while USBL pinned to zone 2 - origins 6 degrees apart. The
    solution walked 672 km west (easting 710,879 -> 63,657, wider than a
    UTM zone is), the output left its own zone entirely, and NOTHING
    flagged it: the run reported "No anomalies detected". NA168 was spared
    only because both sources happened to start in zone 52N.

    Two deliberate choices:

    - The zone comes from the MEDIAN fix, not the first one. A single bad
      leading row is exactly what broke H2060, and a median ignores it
      where a first-row pick or a mean centroid would not.
    - Sources are tried in the order given, and the caller passes USBL
      first. USBL is an absolute acoustic fix; DVL is dead-reckoned and
      drifts (H2060's DVL spans 115 km while its USBL spans 530 m), so DVL
      must never decide the frame when USBL exists.
    """
    for lat_col, lon_col in sources:
        if lat_col not in df.columns or lon_col not in df.columns:
            continue
        valid = df[[lat_col, lon_col]].dropna()
        if valid.empty:
            continue
        lat = float(valid[lat_col].median())
        lon = float(valid[lon_col].median())
        zone_number, hemisphere = determine_utm_zone(lon, lat)
        proj = Proj(utm_proj_string(lon, lat))
        print(f"Pinned UTM Zone {zone_number}{hemisphere[0].upper()} from the "
              f"median {lat_col}/{lon_col} fix ({lat:.5f}, {lon:.5f}); "
              f"every position source uses it.")
        return proj, zone_number, hemisphere, lat, lon
    return None, None, None, None, None


def latlon_to_utm(df, lat_col, lon_col, x_col, y_col, utm_proj, zone_number=None):
    """Convert lat/lon to UTM using the dive's PINNED projection.

    The projection is passed in, never derived here - see
    pin_utm_projection. Returns (converted_count, off_zone_count) where
    off_zone_count is how many fixes naturally belong to a different UTM
    zone. Those still convert correctly (UTM is valid outside its zone,
    the easting just grows), and keeping them in one frame is the point;
    the count exists so the caller can report a track that genuinely
    straddles a boundary.
    """
    if lat_col not in df.columns or lon_col not in df.columns:
        print(f"No {lat_col}/{lon_col} columns present; skipping conversion.")
        df[x_col] = np.nan
        df[y_col] = np.nan
        return 0, 0
    valid_mask = df[lat_col].notna() & df[lon_col].notna()
    valid_count = valid_mask.sum()
    if valid_count == 0:
        print(f"No valid {lat_col}/{lon_col} coordinates found.")
        return 0, 0
    if utm_proj is None:
        print(f"No pinned UTM projection; skipping {lat_col}/{lon_col}.")
        df[x_col] = np.nan
        df[y_col] = np.nan
        return 0, 0

    print(f"Converting {valid_count} points from {lat_col}/{lon_col} to UTM...")

    df[x_col] = np.nan
    df[y_col] = np.nan
    lons = df.loc[valid_mask, lon_col].astype(float).to_numpy()
    lats = df.loc[valid_mask, lat_col].astype(float).to_numpy()
    xs, ys = utm_proj(lons, lats)
    df.loc[valid_mask, x_col] = xs
    df.loc[valid_mask, y_col] = ys
    success_count = int(df[x_col].notna().sum())

    off_zone = 0
    if zone_number is not None:
        natural = np.array([determine_utm_zone(float(lo), float(la))[0]
                            for lo, la in zip(lons, lats)])
        off_zone = int((natural != zone_number).sum())
        if off_zone:
            print(f"NOTE: {off_zone} of {valid_count} {lat_col}/{lon_col} fixes "
                  f"belong to a different UTM zone; converted in the pinned "
                  f"zone {zone_number} anyway so all sources share one frame.")

    print(f"Successfully converted {success_count} of {valid_count} points.")
    if success_count > 0:
        sample = df[[lat_col, lon_col, x_col, y_col]].dropna().head(3)
        print("Sample conversions:")
        for _, row in sample.iterrows():
            print(f"  {row[lat_col]}, {row[lon_col]} -> {row[x_col]}, {row[y_col]}")

    return success_count, off_zone


def process_data(raw_dir, processed_dir):
    """
    Processes the merged ROV data by applying a Kalman filter.

    Args:
        raw_dir (Path or str): Directory containing the raw input file.
                                This should include the dive folder information.
        processed_dir (Path or str): Directory where output files will be saved.
    """
    try:
        # Convert input directories to absolute Path objects.
        raw_dir = Path(raw_dir).resolve()
        processed_dir = Path(processed_dir).resolve()

        expedition, dive = expedition_dive_from_processed_dir(processed_dir)

        # Setup file paths using provided directories.
        input_file = processed_dir / f"{expedition}_{dive}_filtered_datatable.csv"
        output_file = processed_dir / f"{expedition}_{dive}_kalman_filtered_data.csv"

        if not input_file.exists():
            raise FileNotFoundError(f"Input file not found at {input_file}")

        print(f"Reading from: {input_file}")
        print(f"Output will be saved to: {output_file}")

        # Read CSV with timestamp parsing.
        df = pd.read_csv(input_file, parse_dates=["Timestamp"], low_memory=False)

        print(f"Loaded {len(df)} rows from input file.")

        for required in ("Herc_Depth_1", "Heading", "Pitch", "Roll"):
            if required not in df.columns:
                raise KeyError(
                    f"Required column '{required}' missing from {input_file.name}; "
                    f"check the upstream merge (kalman_concat / sensors_sealog outputs)."
                )
        if df.empty:
            raise ValueError(f"{input_file.name} contains no data rows.")

        report = RunReport("kalman_filter", processed_dir)
        report.add_input(input_file, rows=len(df))

        # Filter rows with depth <= -20 m. Note this also drops rows with no
        # depth reading (NaN fails the comparison) -- report both counts.
        original_count = len(df)
        nan_depth = int(df["Herc_Depth_1"].isna().sum())
        df = df[df["Herc_Depth_1"] <= -20]
        print(f"Filtered to {len(df)} rows where depth <= -20m "
              f"(removed {original_count - len(df)} rows, of which {nan_depth} had no depth reading)")
        report.metric("rows_dropped_shallow_or_no_depth", original_count - len(df))
        if nan_depth:
            report.warn("missing-depth",
                        f"{nan_depth} rows had no depth reading and were dropped "
                        f"by the depth <= -20m filter")
        if df.empty:
            report.error("empty-after-filter", "no rows deeper than -20m; nothing to filter")
            report.finalize()
            raise ValueError("No rows deeper than -20m; cannot run the Kalman filter.")

        # Remove duplicate timestamps BEFORE Kalman filter processing.
        # Prefer rows that carry a sealog event (consistent with kalman_concat),
        # and ALWAYS restore chronological order afterwards -- the filter's dt
        # computation assumes monotonically increasing timestamps.
        if df["Timestamp"].duplicated().any():
            print("Duplicate timestamps detected. Removing duplicates (preferring rows with event_value)...")
            if "event_value" in df.columns:
                df = (
                    df.assign(_no_event=df["event_value"].isnull())
                    .sort_values(["Timestamp", "_no_event"], kind="mergesort")
                    .drop_duplicates(subset=["Timestamp"], keep="first")
                    .drop(columns=["_no_event"])
                )
            else:
                df = df.drop_duplicates(subset=["Timestamp"])
            print(f"After deduplication, {len(df)} rows remain.")
        df = df.sort_values("Timestamp", kind="mergesort")

        # ONE pinned projection for every source. USBL first: it is an
        # absolute acoustic fix, while DVL is dead-reckoned and drifts, so
        # DVL must never choose the frame when USBL exists. See
        # pin_utm_projection for the H2060 incident this prevents.
        utm_proj, utm_zone, utm_hemi, pin_lat, pin_lon = pin_utm_projection(
            df, [("Lat_USBL", "Long_USBL"), ("Lat_DVL", "Long_DVL")])
        # Zone label like '53N' -- persisted into the final datatable below so
        # kalman_offset can verify it works in the SAME frame (fe2242c).
        utm_zone_label = (f"{utm_zone}{utm_hemi[0].upper()}"
                          if utm_zone is not None else None)
        usbl_success, usbl_off_zone = latlon_to_utm(
            df, "Lat_USBL", "Long_USBL", "x_usbl", "y_usbl", utm_proj, utm_zone)
        dvl_success, dvl_off_zone = latlon_to_utm(
            df, "Lat_DVL", "Long_DVL", "x_dvl", "y_dvl", utm_proj, utm_zone)
        if utm_zone is not None:
            report.metric("utm_zone", utm_zone_label)
            report.metric("utm_pin_lat", round(pin_lat, 6))
            report.metric("utm_pin_lon", round(pin_lon, 6))
        # A source whose fixes mostly belong elsewhere is the H2060
        # signature: one bad series dragging the frame. Say so loudly
        # rather than letting the filter fuse two coordinate systems.
        for name, off, total in (("USBL", usbl_off_zone, usbl_success),
                                 ("DVL", dvl_off_zone, dvl_success)):
            if total and off:
                frac = off / total
                msg = (f"{off} of {total} {name} fixes ({frac:.0%}) fall outside "
                       f"the pinned UTM zone {utm_zone}")
                if frac > 0.5:
                    report.anomaly("utm-zone-straddle", msg +
                                   " - the majority of this source is in another "
                                   "zone; check it for outliers before trusting "
                                   "the track")
                else:
                    report.warn("utm-zone-straddle", msg +
                                " - converted in the pinned zone so all sources "
                                "share one frame")
        if usbl_success == 0 and dvl_success == 0:
            print("WARNING: No coordinates could be converted to UTM. Check lat/long data.")
            report.anomaly("no-position-data",
                           "no USBL or DVL coordinates could be converted to UTM; "
                           "output positions will be dead-reckoned from the initial state only")
        elif usbl_success == 0:
            report.warn("no-usbl", "no USBL fixes in the dive window; using DVL only")
        elif dvl_success == 0:
            report.warn("no-dvl", "no DVL fixes in the dive window; using USBL only")

        # Convert orientation to radians.
        df["Heading_rad"] = df["Heading"].apply(deg2rad)
        df["Pitch_rad"] = df["Pitch"].apply(deg2rad)
        df["Roll_rad"] = df["Roll"].apply(deg2rad)

        # Process heading separately.
        print("Processing heading data with specialized circular filter...")
        if "Heading" in df.columns:
            df["kalman_yaw_deg"] = filter_heading(df["Heading"].values, window_size=15)
            print(f"Filtered {len(df)} heading values")
        else:
            print("WARNING: No heading data found")
            df["kalman_yaw_deg"] = np.nan

        # Initialize an 8D Kalman Filter (excluding yaw, which is handled separately).
        # Position init prefers USBL, falls back to DVL for USBL-less dives.
        kf = KalmanFilter(dim_x=8, dim_z=1)

        def first_valid(col, fallback_col=None, default=0.0):
            s = df[col].dropna() if col in df.columns else pd.Series(dtype=float)
            if not s.empty:
                return float(s.iloc[0])
            if fallback_col is not None:
                s = df[fallback_col].dropna() if fallback_col in df.columns else pd.Series(dtype=float)
                if not s.empty:
                    return float(s.iloc[0])
            return default

        init_x = first_valid("x_usbl", "x_dvl")
        init_y = first_valid("y_usbl", "y_dvl")
        init_z = df["Herc_Depth_1"].dropna().iloc[0] if not df["Herc_Depth_1"].dropna().empty else 0.0
        init_roll = df["Roll_rad"].dropna().iloc[0] if not df["Roll_rad"].dropna().empty else 0.0
        init_pitch = df["Pitch_rad"].dropna().iloc[0] if not df["Pitch_rad"].dropna().empty else 0.0

        print(f"Initial state: x={init_x}, y={init_y}, z={init_z}")
        kf.x = np.array([init_x, init_y, init_z, init_roll, init_pitch, 0.0, 0.0, 0.0], dtype=float)
        kf.Q = np.diag([
            0.3 ** 2, 0.3 ** 2, 0.3 ** 2,  # Position noise
            0.01 ** 2, 0.01 ** 2,           # Orientation noise (roll, pitch)
            0.05 ** 2, 0.05 ** 2, 0.05 ** 2  # Velocity noise
        ])
        kf.P = np.diag([
            1000, 1000, 1000,
            (math.radians(20)) ** 2,
            (math.radians(20)) ** 2,
            100, 100, 100
        ])

        # Prepare columns for Kalman filter outputs.
        df["kalman_x"] = np.nan
        df["kalman_y"] = np.nan
        df["kalman_lat"] = np.nan
        df["kalman_long"] = np.nan
        df["kalman_depth"] = np.nan
        df["kalman_roll_deg"] = np.nan
        df["kalman_pitch_deg"] = np.nan

        prev_time = None
        recent_usbl_x = []
        recent_usbl_y = []
        if utm_proj is None:
            # No coordinates converted, so there is no meaningful projection.
            # kalman_lat/kalman_long stay NaN rather than being back-projected
            # through an arbitrary default zone.
            print("Warning: No UTM projection could be determined; "
                  "kalman_lat/kalman_long will be empty.")

        print("Starting Kalman filter processing...")
        updates_applied = 0
        usbl_rejected = 0
        dvl_updates = 0
        dvl_rejected = 0

        # Per-step history for the RTS smoother (forward-backward pass).
        xs_hist, Ps_hist, Fs_hist = [], [], []

        def scalar_update(value, state_index, variance):
            """Apply a 1-D measurement update on a single state component."""
            H = np.zeros((1, 8))
            H[0, state_index] = 1.0
            if state_index in (3, 4):
                # Use the equivalent observation nearest the continuous angle
                # estimate: +179 -> -179 is +2 degrees, not -358 degrees.
                value = kf.x[state_index] + wrap_angle(float(value) - kf.x[state_index])
            kf.update(np.array([float(value)]), H=H, R=np.array([[variance]]))

        for i, row in df.iterrows():
            current_time = row["Timestamp"]
            dt = 1.0 if prev_time is None else max((current_time - prev_time).total_seconds(), 0.001)
            prev_time = current_time

            # Build state transition matrix.
            F = np.eye(8)
            F[0, 5] = dt
            F[1, 6] = dt
            F[2, 7] = dt
            kf.F = F
            kf.predict()

            # Depth update.
            if not np.isnan(row.get("Herc_Depth_1", np.nan)):
                scalar_update(row["Herc_Depth_1"], 2, 0.1 ** 2)
                updates_applied += 1

            # USBL gate over the last 20 observed fixes, including rejected ones.
            # This permits reacquisition but can widen the gate during bad bursts;
            # changing that scientific policy requires separate validation.
            if not np.isnan(row.get("x_usbl", np.nan)) and not np.isnan(row.get("y_usbl", np.nan)):
                accept = True
                if len(recent_usbl_x) >= 2:
                    mean_x, mean_y = np.mean(recent_usbl_x), np.mean(recent_usbl_y)
                    std_x, std_y = np.std(recent_usbl_x), np.std(recent_usbl_y)
                    # std == 0 means the recent fixes are identical -- treat as
                    # in-range rather than rejecting the fix outright.
                    if std_x > 0 and abs(row["x_usbl"] - mean_x) > 3 * std_x:
                        accept = False
                    if std_y > 0 and abs(row["y_usbl"] - mean_y) > 3 * std_y:
                        accept = False
                recent_usbl_x.append(row["x_usbl"])
                recent_usbl_y.append(row["y_usbl"])
                if len(recent_usbl_x) > 20:
                    recent_usbl_x.pop(0)
                    recent_usbl_y.pop(0)
                if accept:
                    acc = row.get("Accuracy_USBL", np.nan)
                    usbl_var = (acc if not np.isnan(acc) else 5.0) ** 2
                    scalar_update(row["x_usbl"], 0, usbl_var)
                    scalar_update(row["y_usbl"], 1, usbl_var)
                    updates_applied += 2
                else:
                    usbl_rejected += 1

            # Depth-eligible dead reckoning (<= -30 m), not measured bottom lock.
            # The imported fields contain no per-sample beam/lock validity proof.
            # NOTE: the original condition was `>= -30`, which combined with the
            # depth <= -20 pre-filter meant DVL was only used in a 10 m band and,
            # in practice, never (verified on NA167/H2075: 0 of 48,805 DVL fixes used).
            if not np.isnan(row.get("x_dvl", np.nan)) and not np.isnan(row.get("y_dvl", np.nan)):
                if row["Herc_Depth_1"] <= -30:
                    # INNOVATION GATE. USBL has had a 3-sigma gate since the
                    # start; DVL had NONE, so a DVL fix entered at 3 m sigma
                    # no matter how far it sat from the state. NA165 H2060
                    # (2026-08-14): its DVL series is anchored 250 km
                    # off-site for the first stretch and JUMPS into place -
                    # only 3 steps exceed 100 m, the rest are p99 0.4 m - and
                    # every one of those wrong-anchor rows was accepted,
                    # dragging the solution 113 km and making the good USBL
                    # fixes look like outliers (1,403 of them gated out).
                    #
                    # The gate is against the STATE, not against recent DVL
                    # fixes: the bad stretch is internally consistent, so a
                    # self-referential gate accepts it. The state is anchored
                    # by USBL (init prefers x_usbl), which is what makes the
                    # disagreement visible.
                    #
                    # It only ever catches JUMPS. Where DVL legitimately
                    # dead-reckons with no USBL, the state travels with it and
                    # the innovation stays small - so this does not reinstate
                    # the old "DVL never used" bug.
                    innovation = math.hypot(float(row["x_dvl"]) - kf.x[0],
                                            float(row["y_dvl"]) - kf.x[1])
                    if innovation <= DVL_INNOVATION_GATE_M:
                        scalar_update(row["x_dvl"], 0, 3.0 ** 2)
                        scalar_update(row["y_dvl"], 1, 3.0 ** 2)
                        updates_applied += 2
                        dvl_updates += 1
                    else:
                        dvl_rejected += 1

            # Orientation updates.
            if not np.isnan(row.get("Roll_rad", np.nan)):
                scalar_update(row["Roll_rad"], 3, 0.017 ** 2)
                updates_applied += 1

            if not np.isnan(row.get("Pitch_rad", np.nan)):
                scalar_update(row["Pitch_rad"], 4, 0.017 ** 2)
                updates_applied += 1

            # Keep roll/pitch continuous through the linear RTS backward pass.
            # Wrapping here would reintroduce a 2*pi jump into its residuals.
            # Only the published degree columns are wrapped below.
            xs_hist.append(kf.x.copy())
            Ps_hist.append(kf.P.copy())
            Fs_hist.append(F)

        print(f"Kalman filter processing complete. Applied {updates_applied} updates.")
        if usbl_rejected:
            print(f"USBL outlier gate rejected {usbl_rejected} fixes.")

        # RTS (Rauch-Tung-Striebel) smoother: a backward pass that removes the
        # causal filter's lag by conditioning every state on the whole dive.
        Xs = np.array(xs_hist)
        if len(Xs) >= 2:
            print("Running RTS smoother (backward pass)...")
            Xs_smooth, _, _, _ = kf.rts_smoother(
                Xs, np.array(Ps_hist), Fs=Fs_hist, Qs=[kf.Q] * len(Xs)
            )
        else:
            Xs_smooth = Xs

        # Write smoothed states back (df is in the same order the loop ran).
        df["kalman_x"] = Xs_smooth[:, 0]
        df["kalman_y"] = Xs_smooth[:, 1]
        df["kalman_depth"] = Xs_smooth[:, 2]
        df["kalman_roll_deg"] = np.degrees(wrap_angle(Xs_smooth[:, 3]))
        df["kalman_pitch_deg"] = np.degrees(wrap_angle(Xs_smooth[:, 4]))
        if utm_proj is not None:
            lons, lats = utm_proj(Xs_smooth[:, 0], Xs_smooth[:, 1], inverse=True)
            df["kalman_lat"] = lats
            df["kalman_long"] = lons

        # Convert Timestamp back to ISO8601.
        df["Timestamp"] = pd.to_datetime(df["Timestamp"], utc=True).apply(
            lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")
        )

        # Ensure the processed directory exists.
        processed_dir.mkdir(parents=True, exist_ok=True)

        # Record the pinned UTM zone in the frame so downstream stages
        # (kalman_offset) reuse the SAME zone instead of re-deriving it.
        # Label form like '53N' -- what proj_string_for_zone_label parses.
        df["utm_zone"] = utm_zone_label if utm_zone_label is not None else np.nan

        # Save filtered data. On a PermissionError (e.g. the file is open in
        # Excel), retry via a temp name + atomic replace into the SAME
        # prefixed path -- never write an unprefixed fallback file to the
        # cwd, because nothing downstream reads it. If the replace also
        # fails, fail loudly instead of pretending success.
        try:
            df.to_csv(output_file, index=False, mode='w')
            print(f"\nSaved Kalman-filtered data to {output_file}")
        except PermissionError:
            tmp_output = output_file.with_name(output_file.name + ".tmp")
            df.to_csv(tmp_output, index=False, mode='w')
            try:
                os.replace(tmp_output, output_file)
            except OSError as replace_err:
                try:
                    tmp_output.unlink()
                except OSError:
                    pass
                raise PermissionError(
                    f"Cannot write {output_file} (locked by another process?). "
                    f"Close whatever has it open and rerun this stage."
                ) from replace_err
            print(f"\nSaved Kalman-filtered data to {output_file} "
                  f"(via temp-name + rename after a permission error).")

        # Build and save the final datatable.
        final_columns = [
            "Timestamp", "Vehicle", "x_usbl", "y_usbl", "x_dvl", "y_dvl",
            "Heading_rad", "Pitch_rad", "Roll_rad", "kalman_yaw_deg",
            "kalman_x", "kalman_y", "kalman_lat", "kalman_long", "kalman_depth",
            "kalman_roll_deg", "kalman_pitch_deg", "O2_Concentration", "O2_Saturation",
            "Temperature", "Conductivity", "Pressure", "Salinity", "Sound_Velocity",
            "event_value", "event_free_text", "event_option.channel", "event_option.milestone",
            "event_option.rating", "event_option.vehicle",
            "vehicleRealtimeDualHDGrabData.camera_name_2_uom", "vehicleRealtimeDualHDGrabData.camera_name_2_value",
            "vehicleRealtimeDualHDGrabData.camera_name_uom", "vehicleRealtimeDualHDGrabData.camera_name_value",
            "vehicleRealtimeDualHDGrabData.filename_2_uom", "vehicleRealtimeDualHDGrabData.filename_2_value",
            "vehicleRealtimeDualHDGrabData.filename_uom", "vehicleRealtimeDualHDGrabData.filename_value",
            "utm_zone"
        ]
        for col in final_columns:
            if col not in df.columns:
                df[col] = np.nan

        final_df = df[final_columns]
        final_output_file = processed_dir / f"{expedition}_{dive}_final_datatable.csv"
        final_df.to_csv(final_output_file, index=False, quoting=csv.QUOTE_ALL)
        print(f"Saved final datatable to {final_output_file}")

        # Did the SOLUTION stay inside its own zone? A UTM zone is ~668 km
        # wide at the equator and eastings run 100k-900k; a track that
        # leaves that has diverged, whatever the inputs looked like. H2060
        # produced an easting span of 672 km and reported "No anomalies
        # detected" - the run looked clean end to end (2026-08-14).
        if "kalman_x" in df.columns and df["kalman_x"].notna().any():
            ex = df["kalman_x"].dropna()
            span_km = float(ex.max() - ex.min()) / 1000.0
            report.metric("kalman_easting_span_km", round(span_km, 1))
            if span_km > 500.0:
                report.anomaly(
                    "solution-diverged",
                    f"filtered easting spans {span_km:.0f} km - a UTM zone is "
                    f"only ~668 km wide, so the solution has left its own "
                    f"zone. The track is NOT usable; check that every "
                    f"position source shares one frame and that no source "
                    f"carries far-field outliers.")
            elif not ((ex.min() > 100_000) and (ex.max() < 900_000)):
                report.anomaly(
                    "solution-out-of-zone",
                    f"filtered eastings run {ex.min():,.0f}..{ex.max():,.0f}, "
                    f"outside the 100k-900k a UTM zone spans - the track has "
                    f"drifted out of the pinned zone")

        report.metric("rows_out", len(df))
        report.metric("measurement_updates", updates_applied)
        report.metric("dvl_position_updates", dvl_updates)
        report.metric("dvl_fixes_gated_out", dvl_rejected)
        report.metric("usbl_fixes_gated_out", usbl_rejected)
        report.metric("usbl_gate_history", "last_20_observed_fixes_including_rejections")
        report.metric("dvl_bottom_lock_evidence", "unavailable; depth eligibility is not measured lock")
        report.metric("orientation_filter", "nearest_branch_updates_continuous_rts_output_wrap")
        report.metric("rts_smoother", "applied" if len(Xs) >= 2 else "skipped (too few rows)")
        if dvl_updates == 0 and dvl_success > 0:
            report.anomaly("dvl-unused",
                           f"{dvl_success} DVL fixes were available but none were used: "
                           f"{dvl_rejected} rejected by the {DVL_INNOVATION_GATE_M:.0f} m "
                           f"innovation gate, the rest failed the depth <= -30m gate -- "
                           f"check the depth channel and the DVL anchor")
        if usbl_rejected > max(50, 0.10 * max(usbl_success, 1)):
            report.warn("usbl-gate",
                        f"outlier gate rejected {usbl_rejected} of {usbl_success} USBL fixes "
                        f"(unusually high; USBL may be noisy this dive)")
        report.add_output(output_file, rows=len(df))
        report.add_output(final_output_file, rows=len(final_df))
        report.finalize()

        print("Processing complete. All UTM and Kalman-filtered data included in output.")
    except Exception as e:
        # Print the error and traceback for the operator, then RE-RAISE
        # (fixed identically by 0668a3e and fe2242c). Returning 1 here made
        # this the only module whose failure could not reach the
        # orchestrator: main_kalman discarded the return value, printed
        # "Finished processing kalman_filter." and scored it "done", after
        # which kalman_offset happily consumed the PREVIOUS run's
        # final_datatable.csv and wrote a fresh-looking offset file from
        # stale positions. Every other processor raises; so does this one now.
        print(f"ERROR: {e}")
        print(traceback.format_exc())
        raise
    return 0


if __name__ == "__main__":
    # For testing purposes, if run directly, allow optional command-line arguments.
    # Otherwise, default to current directory as raw_dir and a "processed" subdirectory.
    if len(sys.argv) >= 3:
        raw_directory = Path(sys.argv[1])
        processed_directory = Path(sys.argv[2])
    else:
        raw_directory = Path.cwd().resolve()
        processed_directory = raw_directory / "processed"
    processed_directory.mkdir(parents=True, exist_ok=True)
    exit_code = process_data(raw_directory, processed_directory)
    sys.exit(exit_code)
