"""
Standalone Georeference Images Script
Processes underwater images from multiple dives and generates RealityScan flight logs.
Copies matched images into dive-specific subdirectories.
Validates copied images and removes corrupt files after confirmation.
Optimized with multiprocessing and binary search for speed.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import glob
import math
import os
import re
import shutil
import traceback
from collections import defaultdict
from datetime import datetime
from multiprocessing import Pool, cpu_count

# ONE rig table, shared with the georeference module. geoall used to carry a
# parallel copy that had no WCA cameras and claimed 3 deg orientation
# accuracy where the module claims 15 - two contradictory answers for the
# same rig, in the file the docs call canonical (review finding M4).
from modules.georeference.georeference_images import MOUNTS as _MOUNTS
from modules.georeference.georeference_images import (
    PRIOR_ACCURACY_DEFAULTS as _ACCURACY_DEFAULTS,
    ASSUMED_MOUNT_DEFAULTS as _ASSUMED_MOUNT,
    assumed_pitch_prior as _assumed_pitch_prior)
from modules import camera_registry as _camera_registry

import utm
from PIL import Image
from tqdm import tqdm

try:
    from module_base.settings_store import SettingsStore
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
    from module_base.settings_store import SettingsStore

# Default paths (offered as prompt defaults on first run; afterwards the
# last-entered values from rs_settings.json are offered instead)
DEFAULT_IMAGE_BASE_DIR = r"Z:\NA173_All_Images_Corrected\NA173\sorted"
DEFAULT_ROV_DATA_DIR = r"Z:\alldatatables"
DEFAULT_OUTPUT_DIR = r"Z:\alldatatables"

# Timestamp formats
# superseded-by modules/cameras.json families[].timestamp_formats - pending migration step (c+)
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
WCA_FILENAME_TIMESTAMP_FORMAT = "%Y%m%d%H%M%S"
ZEUSS_FILENAME_TIMESTAMP_FORMAT = "%Y%m%d%H%M%S"
WCA2025_FILENAME_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"

# Fixed parameters
MAGNETIC_DECLINATION_DEG = 0.0
MATCH_THRESHOLD_SEC = 2.0
NUM_WORKERS = max(1, cpu_count() - 1)  # Leave one CPU free

# Pre-compiled regex patterns for performance
REGEX_WCA2025 = re.compile(r'(\d{8}T\d{6}Z)')
REGEX_WCA_ZEUSS = re.compile(r'(\d{14})')


def wrap360(angle_deg: float) -> float:
    """Wrap angle to [0, 360) range."""
    return angle_deg % 360.0


def get_camera_type(filename: str) -> str:
    """Identify camera type from filename."""
    # superseded-by modules/cameras.json families (display-only labels, no WCA branch) - pending migration step (c+)
    filename_lower = filename.lower()

    if filename_lower.startswith('camupper'):
        return 'CamUpper'
    elif filename_lower.startswith('cammid'):
        return 'CamMid'
    elif filename_lower.startswith('camlower'):
        return 'CamLower'
    elif '_herc_' in filename_lower or 'herc' in filename_lower:
        return 'Zeuss/HERC'
    else:
        return 'Unknown'


def get_camera_pitch_accuracy(filename: str, assume_pitch: bool = True,
                              pitch_deg: float | None = None,
                              accuracy_deg: float | None = None) -> float | None:
    """Pitch accuracy (degrees) from the shared MOUNTS table, or None when
    the mount has never been measured.

    This was a stale parallel table the M4/M5 unification missed (audit #6,
    2026-07-28): lever arm and pitch offset were routed through MOUNTS while
    pitch ACCURACY stayed on the old prefix chain, so WCA P/C files fell to a
    10.0 default against the module's 15.0, and Zeuss got 10.0 against 30.0 -
    3x overconfidence on the mount with the least ground truth. PD-0
    established that over-tight orientation accuracy FRAGMENTS the solve.

    A MEASURED mount always wins. With none, this falls back to the house
    convention (ASSUMED_MOUNT_DEFAULTS, owner-stated 2026-08-31): 10 deg down
    at 30 deg accuracy. The accuracy is deliberately loose - the 2026-08-07
    audit removed a 0 deg / 10 deg fallback precisely because asserting
    unmeasured geometry at tight confidence FRAGMENTS solves (PD-0), and that
    half of its reasoning still holds. VOYIS families never take the fallback.

    Must track get_camera_pitch_offset exactly: a pitch with an empty accuracy
    (or the reverse) is a malformed flight-log row.
    """
    mount = _mount(filename)
    if mount and 'p_acc' in mount:
        return float(mount['p_acc'])
    return _assumed_pitch_prior(_camera_registry.family(filename),
                                enabled=assume_pitch,
                                pitch_deg=pitch_deg,
                                accuracy_deg=accuracy_deg)[1]



def _mount(filename: str) -> dict | None:
    """Shared mount lookup; None when the family or its geometry is unknown."""
    fam = _camera_registry.family(filename)
    return _MOUNTS.get(fam) if fam else None


def get_camera_pitch_offset(filename: str, assume_pitch: bool = True,
                            pitch_deg: float | None = None,
                            accuracy_deg: float | None = None) -> float | None:
    """Camera down-tilt from the vehicle forward axis, in degrees, or None
    when the mount has never been measured (= no pitch prior).

    Delegates to the shared table; the local prefix chain had no WCA branch so
    Cinema silently lost its 45 deg down-look in standalone runs.

    A MEASURED mount always wins. With none, this falls back to the house
    convention (ASSUMED_MOUNT_DEFAULTS: 10 deg down, owner-stated 2026-08-31),
    except for the VOYIS families, whose poses come from the COLMAP bridge -
    a vehicle-nav prior there is the wrong pipeline, not a missing measurement.
    """
    mount = _mount(filename)
    if mount is not None:
        return mount['pitch']
    return _assumed_pitch_prior(_camera_registry.family(filename),
                                enabled=assume_pitch,
                                pitch_deg=pitch_deg,
                                accuracy_deg=accuracy_deg)[0]


def get_camera_offsets(filename: str) -> tuple[float, float, float]:
    """(forward, lateral, down) lever arm in metres, or zeros when unknown.

    Delegates to the SHARED table in modules/georeference/georeference_images.py.
    This function previously had no WCA branch at all, so every P###C/C###C
    still fell through to a zero lever arm - and geoall is the georeferencer the
    docs call canonical.
    """
    mount = _mount(filename)
    if mount is None:
        return (0.0, 0.0, 0.0)
    return (mount['fwd'], mount['lat'], mount['down'])


def apply_camera_position_offset(utm_x: float | None, utm_y: float | None,
                                 altitude: float | None, heading_deg: float | None,
                                 forward_m: float, lateral_m: float, down_m: float) -> tuple[
    float | None, float | None, float | None]:
    """Apply camera position offset from vehicle center to world coordinates."""
    if utm_x is None or utm_y is None or heading_deg is None:
        return utm_x, utm_y, altitude

    heading_rad = math.radians(heading_deg)

    east_offset = forward_m * math.sin(heading_rad)
    north_offset = forward_m * math.cos(heading_rad)

    east_offset += lateral_m * math.cos(heading_rad)
    north_offset += lateral_m * (-math.sin(heading_rad))

    adjusted_utm_x = utm_x + east_offset
    adjusted_utm_y = utm_y + north_offset
    adjusted_altitude = altitude - down_m if altitude is not None else None

    return adjusted_utm_x, adjusted_utm_y, adjusted_altitude


def convert_to_rc_orientation(heading_mag: float | None, pitch_vehicle: float | None,
                              roll_vehicle: float | None, camera_offset: float,
                              decl_deg: float) -> tuple[float | None, float | None, float | None]:
    """Convert vehicle orientation to RealityScan conventions."""
    if heading_mag is not None:
        true_heading = heading_mag + decl_deg
        rc_yaw = wrap360(true_heading)
    else:
        rc_yaw = None

    # camera_offset None = no measured mount = no pitch prior at all.
    if pitch_vehicle is not None and camera_offset is not None:
        camera_pitch_from_horiz = pitch_vehicle - camera_offset
        rc_pitch = 90.0 + camera_pitch_from_horiz
    else:
        rc_pitch = None

    rc_roll = roll_vehicle

    return rc_yaw, rc_pitch, rc_roll


def parse_timestamp_from_filename(filename: str) -> datetime | None:
    """
    Extract and parse the timestamp from an image filename.
    Handles formats: 20250705T130954Z, 20250705130954, and variations.
    """
    base_name = os.path.splitext(filename)[0]

    # Try WCA2025 format: YYYYMMDDTHHMMSSZ (e.g., 20250705T130954Z)
    try:
        match = REGEX_WCA2025.search(base_name)
        if match:
            return datetime.strptime(match.group(1), WCA2025_FILENAME_TIMESTAMP_FORMAT)
    except ValueError as e:
        print(f"Debug: Failed to parse WCA2025 format from {filename}: {e}")

    # Try WCA/Zeuss format: YYYYMMDDHHMMSS (14 digits, e.g., 20250705130954)
    try:
        match = REGEX_WCA_ZEUSS.search(base_name)
        if match:
            return datetime.strptime(match.group(1), WCA_FILENAME_TIMESTAMP_FORMAT)
    except ValueError as e:
        print(f"Debug: Failed to parse WCA format from {filename}: {e}")

    return None


def convert_to_utm(lat, lon, utm_zone_cache: dict):
    """Convert latitude and longitude to UTM, PINNED to the first row's zone.

    The zone used to latch on the first converted row while every later row
    was still converted in ITS OWN natural zone, so a track crossing a zone
    boundary got a silent ~500 km easting jump (an equator crossing ~9,900 km
    of northing) inside a log whose filename claimed one zone
    (audit 2026-08-07). Mirrors GeoreferenceImages.__convert_to_utm; the
    crossing count rides in utm_zone_cache['crossings'] for the summary.
    """
    if lat is None or lon is None:
        return None, None
    try:
        if 'force' not in utm_zone_cache:
            easting, northing, zone_number, zone_letter = utm.from_latlon(lat, lon)
            utm_zone_cache['force'] = (zone_number, zone_letter)
            utm_zone_cache['zone'] = f"{zone_number}{zone_letter}"
            return easting, northing
        zone_number, zone_letter = utm_zone_cache['force']
        if utm.latlon_to_zone_number(lat, lon) != zone_number:
            utm_zone_cache['crossings'] = utm_zone_cache.get('crossings', 0) + 1
        return utm.from_latlon(lat, lon, force_zone_number=zone_number,
                               force_zone_letter=zone_letter)[:2]
    except Exception as e:
        print(f"Error: Failed to convert to UTM coordinates: {e}")
        return None, None


def extract_dive_number(filename: str) -> str | None:
    """Extract dive number from ROV data filename (e.g., NA173_H2103b_final_datatable.csv)."""
    match = re.match(r'(NA\d+_[^_]+)', filename)
    if match:
        return match.group(1)
    return None


def find_all_edt_directories(base_dir: str) -> list[str]:
    """Find all 'edt' subdirectories under the base directory."""
    edt_dirs = []
    for root, dirs, files in os.walk(base_dir):
        if 'edt' in dirs:
            edt_path = os.path.join(root, 'edt')
            edt_dirs.append(edt_path)
    return edt_dirs


def find_rov_datafiles(data_dir: str) -> dict[str, str]:
    """Find all ROV datafiles and map dive numbers to file paths.

    A dive directory typically holds several CSVs for the same dive
    (USBL, DVL, kalman assessment, sensor merges...); the merged
    ``*final_datatable.csv`` is the authoritative navigation source, so
    it is preferred whenever more than one file matches a dive number.
    """
    candidates: dict[str, list[str]] = defaultdict(list)
    for filepath in sorted(glob.glob(os.path.join(data_dir, "*.csv"))):
        filename = os.path.basename(filepath)
        dive_number = extract_dive_number(filename)
        if dive_number:
            candidates[dive_number].append(filepath)
        else:
            print(f"Warning: Could not extract dive number from {filename}")

    dive_files = {}
    for dive_number, paths in candidates.items():
        finals = [p for p in paths if 'final_datatable' in os.path.basename(p).lower()]
        if finals:
            chosen = finals[0]
        else:
            chosen = paths[0]
        dive_files[dive_number] = chosen
        if len(paths) > 1:
            ignored = [os.path.basename(p) for p in paths if p != chosen]
            print(f"Note: {dive_number}: using {os.path.basename(chosen)}; "
                  f"ignoring {len(ignored)} other CSV(s): {', '.join(ignored[:4])}"
                  + ('...' if len(ignored) > 4 else ''))

    return dive_files


def read_csv_data(filename: str) -> list[dict]:
    """Read and parse CSV data from a file."""
    data_rows = []
    try:
        with open(filename, "r") as csvfile:
            reader = csv.reader(csvfile, delimiter=',', quotechar='"')
            header = next(reader)

            # Strip quotes from header names
            header = [h.strip().strip('"') for h in header]
            idx_map = {name: index for index, name in enumerate(header)}

            if 'Timestamp' not in idx_map:
                print(f"Error: 'Timestamp' column not found in CSV. Available columns: {header}")
                return []

            for row in reader:
                # Strip quotes and whitespace from values
                row = [val.strip().strip('"') for val in row]

                try:
                    timestamp_str = row[idx_map['Timestamp']]
                    data_rows.append({
                        "TIME": datetime.strptime(timestamp_str, TIMESTAMP_FORMAT),
                        "LAT": float(row[idx_map['kalman_lat']]) if row[idx_map['kalman_lat']] else None,
                        "LONG": float(row[idx_map['kalman_long']]) if row[idx_map['kalman_long']] else None,
                        "DEPTH": -abs(float(row[idx_map['kalman_depth']])) if row[idx_map['kalman_depth']] else None,
                        "HEADING_MAG": float(row[idx_map['kalman_yaw_deg']]) if row[idx_map['kalman_yaw_deg']] else None,
                        "PITCH": float(row[idx_map['kalman_pitch_deg']]) if row[idx_map['kalman_pitch_deg']] else None,
                        "ROLL": float(row[idx_map['kalman_roll_deg']]) if row[idx_map['kalman_roll_deg']] else None
                    })
                except (ValueError, KeyError) as e:
                    continue

    except Exception as e:
        print(f"Error: Failed to process CSV file {filename}: {e}")
        raise e
    return data_rows


def read_image_filenames(edt_dirs: list[str]) -> list[dict]:
    """
    Read all JPEG image filenames from edt directories and generate
    a pre-dive camera timestamp summary. No validation performed.
    """
    image_data = []
    jpeg_extensions = {'.jpg', '.jpeg', '.png'}
    all_jpeg_files = []

    seen_files = set()
    for edt_dir in set(edt_dirs):
        if not os.path.isdir(edt_dir):
            continue
        for filename in os.listdir(edt_dir):
            if filename.startswith("."):
                continue
            ext = os.path.splitext(filename)[1].lower()
            if ext in jpeg_extensions:
                full_path = os.path.join(edt_dir, filename)
                if full_path in seen_files:
                    continue
                seen_files.add(full_path)
                all_jpeg_files.append((filename, full_path))

    total_files = len(all_jpeg_files)
    print(f"\nReading {total_files} images from {len(set(edt_dirs))} edt directories...")

    ts_parse_failures = 0
    failed_examples = []
    camera_groups = defaultdict(list)

    for filename, full_path in tqdm(all_jpeg_files, desc="Reading Image Data"):
        timestamp = parse_timestamp_from_filename(filename)
        if timestamp:
            image_data.append({
                "FILENAME": filename,
                "FULL_PATH": full_path,
                "TIMESTAMP": timestamp
            })
            cam_type = get_camera_type(filename)
            camera_groups[cam_type].append(timestamp)
        else:
            ts_parse_failures += 1
            if len(failed_examples) < 5:
                failed_examples.append(filename)

    print("\nCamera Timestamp Summary (pre-dive processing):")
    for cam_type, timestamps in camera_groups.items():
        if timestamps:
            start_time = min(timestamps)
            end_time = max(timestamps)
            duration = end_time - start_time
            print(f"  {cam_type:15s}  Start: {start_time}, End: {end_time}, Duration: {duration}")
        else:
            print(f"  {cam_type:15s}  No timestamps available")

    print(f"\n  Valid images with timestamps: {len(image_data)}")
    print(f"  Timestamp parse failures: {ts_parse_failures}")
    if ts_parse_failures > 0:
        print("Examples of failed filenames:")
        for fn in failed_examples:
            print(f"  {fn}")

    return image_data


def find_closest_timestamp_index(times: list[datetime], target_time: datetime) -> int:
    """
    Binary search for the index of the closest timestamp in a pre-sorted
    list. The caller extracts ``times`` ONCE per dive - rebuilding it here
    per lookup (as an earlier version did) degenerates the whole search
    back to O(N) per image.
    """
    if not times:
        return -1

    # Find insertion point
    idx = bisect.bisect_left(times, target_time)

    # Check boundary conditions
    if idx == 0:
        return 0
    if idx == len(times):
        return len(times) - 1

    # Compare with neighbors to find closest
    before = times[idx - 1]
    after = times[idx]

    if abs(target_time - before) <= abs(target_time - after):
        return idx - 1
    return idx


def estimate_location(image_data: list[dict], data_rows: list[dict], utm_zone_cache: dict) -> tuple[list[dict], dict]:
    """Estimate location and orientation for each image using binary search."""
    stats = {
        'matches_made': 0,
        'exact_matches': 0,
        'matches_0_4': 0,
        'matches_4_15': 0,
        'matches_gt15': 0,
        'rejected_time': 0,
        'accepted_missing_utm': 0,
        'accepted_missing_orientation': 0,
        'camera_type_counts': defaultdict(int)
    }

    matched_images = []
    rejection_examples = []

    # Sort once, extract the timestamp key list once - the binary search
    # below assumes both
    data_rows.sort(key=lambda row: row["TIME"])
    times = [row["TIME"] for row in data_rows]

    for image in tqdm(image_data, desc="Estimating Location"):
        if not data_rows:
            continue

        # Use binary search instead of linear scan
        closest_idx = find_closest_timestamp_index(times, image["TIMESTAMP"])
        if closest_idx < 0:
            continue

        closest_match = data_rows[closest_idx]
        time_diff = abs(closest_match["TIME"] - image["TIMESTAMP"])
        diff_sec = time_diff.total_seconds()

        # Contiguous buckets - the old ==0 / 1-4 / 5-15 / >15 split dropped
        # deltas in (0,1) and (4,5)
        if diff_sec == 0:
            stats['exact_matches'] += 1
        elif diff_sec <= 4:
            stats['matches_0_4'] += 1
        elif diff_sec <= 15:
            stats['matches_4_15'] += 1
        else:
            stats['matches_gt15'] += 1

        if diff_sec > MATCH_THRESHOLD_SEC:
            stats['rejected_time'] += 1
            if len(rejection_examples) < 3:
                rejection_examples.append({
                    'filename': image["FILENAME"],
                    'image_time': image["TIMESTAMP"],
                    'closest_csv_time': closest_match["TIME"],
                    'diff_sec': diff_sec
                })
            continue

        lat, lon = closest_match.get("LAT"), closest_match.get("LONG")
        utm_x, utm_y = convert_to_utm(lat, lon, utm_zone_cache)

        forward_m, lateral_m, down_m = get_camera_offsets(image["FILENAME"])

        camera_utm_x, camera_utm_y, camera_alt = apply_camera_position_offset(
            utm_x, utm_y, closest_match.get("DEPTH"),
            closest_match.get("HEADING_MAG"),
            forward_m, lateral_m, down_m
        )

        camera_type = get_camera_type(image["FILENAME"])
        stats['camera_type_counts'][camera_type] += 1

        matched_image = {
            "FILENAME": image["FILENAME"],
            "FULL_PATH": image["FULL_PATH"],
            "TIMESTAMP": image["TIMESTAMP"],
            "LAT": lat,
            "LONG": lon,
            "UTM_X": camera_utm_x,
            "UTM_Y": camera_utm_y,
            "ALTITUDE_EST": camera_alt,
            "HEADING_MAG": closest_match.get("HEADING_MAG"),
            "PITCH_VEHICLE": closest_match.get("PITCH"),
            "ROLL_VEHICLE": closest_match.get("ROLL"),
            "CAMERA_TYPE": camera_type
        }

        matched_images.append(matched_image)
        stats['matches_made'] += 1

        if camera_utm_x is None or camera_utm_y is None:
            stats['accepted_missing_utm'] += 1

        if (closest_match.get("HEADING_MAG") is None or
                closest_match.get("PITCH") is None or
                closest_match.get("ROLL") is None):
            stats['accepted_missing_orientation'] += 1

    if rejection_examples:
        print("\nSample rejections (image time vs closest CSV time):")
        for ex in rejection_examples:
            print(f"  {ex['filename']}")
            print(f"    Image: {ex['image_time']}")
            print(f"    CSV:   {ex['closest_csv_time']}")
            print(f"    Diff:  {ex['diff_sec']:.1f} seconds")

    return matched_images, stats


def _copy_single_image(args: tuple) -> dict:
    """
    Helper function to copy a single image. Used for multiprocessing.
    Returns dict with success status and metadata.
    """
    image, dive_number, output_dir = args
    src_path = image["FULL_PATH"]
    dive_image_dir = os.path.join(output_dir, dive_number)

    # Create camera-specific subdirectory
    camera_subdir = os.path.join(dive_image_dir, image["CAMERA_TYPE"])
    os.makedirs(camera_subdir, exist_ok=True)

    dst_path = os.path.join(camera_subdir, image["FILENAME"])

    try:
        if os.path.exists(dst_path):
            if os.path.getsize(src_path) == os.path.getsize(dst_path):
                return {'success': True, 'camera_type': image["CAMERA_TYPE"], 'skipped': True}

        shutil.copy2(src_path, dst_path)
        return {'success': True, 'camera_type': image["CAMERA_TYPE"], 'skipped': False}
    except Exception as e:
        return {'success': False, 'error': str(e), 'filename': image["FILENAME"]}


def copy_matched_images(matched_images: list[dict], dive_number: str, output_dir: str) -> tuple[int, int, dict]:
    """Copy matched images to dive-specific subdirectory using multiprocessing."""
    dive_image_dir = os.path.join(output_dir, dive_number)

    if not os.path.exists(dive_image_dir):
        os.makedirs(dive_image_dir)
        print(f"Created directory: {dive_image_dir}")

    copied_count = 0
    failed_count = 0
    camera_copy_counts = defaultdict(int)

    print(f"Copying {len(matched_images)} matched images using {NUM_WORKERS} workers...")

    # Prepare arguments for multiprocessing
    copy_args = [(img, dive_number, output_dir) for img in matched_images]

    # Use multiprocessing pool
    with Pool(NUM_WORKERS) as pool:
        results = list(tqdm(
            pool.imap(_copy_single_image, copy_args),
            total=len(copy_args),
            desc="Copying Images"
        ))

    # Process results
    for result in results:
        if result['success']:
            copied_count += 1
            camera_copy_counts[result['camera_type']] += 1
        else:
            print(f"  Error copying {result['filename']}: {result['error']}")
            failed_count += 1

    return copied_count, failed_count, camera_copy_counts


def _validate_single_image(filepath: str) -> dict:
    """
    Helper function to validate a single image. Used for multiprocessing.
    Returns dict with validation results.
    """
    filename = os.path.basename(filepath)

    try:
        with Image.open(filepath) as img:
            img.verify()

        with Image.open(filepath) as img:
            img.load()

        return {'valid': True, 'filename': filename, 'filepath': filepath}
    except Exception as e:
        return {'valid': False, 'filename': filename, 'filepath': filepath, 'error': str(e)}


def validate_and_cleanup_images(output_dir: str, dive_numbers: list[str],
                                delete_corrupt: str = 'ask') -> dict:
    """
    Validate all copied images across all dives using multiprocessing.
    Searches in camera-specific subdirectories.
    Offers to delete corrupt files. Returns validation statistics.

    ``delete_corrupt`` is 'ask' (prompt, EOF-safe -> keep), 'yes' or 'no'.
    """
    print(f"\n{'='*80}")
    print("IMAGE VALIDATION AND CLEANUP")
    print(f"{'='*80}")

    all_corrupt_files = []
    validation_stats = {
        'total_checked': 0,
        'valid_images': 0,
        'corrupt_images': 0,
        'per_dive_corrupt': defaultdict(list)
    }

    # Collect all image files to validate from camera subdirectories
    all_image_files = []
    dive_file_map = {}  # Map filepath to dive_number

    for dive_number in dive_numbers:
        dive_image_dir = os.path.join(output_dir, dive_number)
        if not os.path.exists(dive_image_dir):
            continue

        # Walk through camera subdirectories
        for camera_subdir in os.listdir(dive_image_dir):
            camera_path = os.path.join(dive_image_dir, camera_subdir)
            if not os.path.isdir(camera_path):
                continue

            jpeg_files = [os.path.join(camera_path, f) for f in os.listdir(camera_path)
                         if f.lower().endswith(('.jpg', '.jpeg', '.png'))]

            for filepath in jpeg_files:
                all_image_files.append(filepath)
                dive_file_map[filepath] = dive_number

    if not all_image_files:
        print("No images found to validate.")
        return validation_stats

    validation_stats['total_checked'] = len(all_image_files)
    print(f"\nValidating {len(all_image_files)} images across {len(dive_numbers)} dives using {NUM_WORKERS} workers...")

    # Use multiprocessing pool for validation
    with Pool(NUM_WORKERS) as pool:
        results = list(tqdm(
            pool.imap(_validate_single_image, all_image_files),
            total=len(all_image_files),
            desc="Validating Images"
        ))

    # Process results
    for result in results:
        if result['valid']:
            validation_stats['valid_images'] += 1
        else:
            validation_stats['corrupt_images'] += 1
            dive_number = dive_file_map[result['filepath']]
            validation_stats['per_dive_corrupt'][dive_number].append(result['filename'])
            all_corrupt_files.append({
                'dive': dive_number,
                'filename': result['filename'],
                'path': result['filepath'],
                'error': result['error']
            })

    print(f"\n{'='*80}")
    print("VALIDATION RESULTS")
    print(f"{'='*80}")
    print(f"Total Images Checked:   {validation_stats['total_checked']}")
    print(f"Valid Images:           {validation_stats['valid_images']}")
    print(f"Corrupt Images:         {validation_stats['corrupt_images']}")

    if all_corrupt_files:
        print(f"\nCorrupt images found in {len(validation_stats['per_dive_corrupt'])} dives:")
        for dive_number, corrupt_files in validation_stats['per_dive_corrupt'].items():
            print(f"\n  {dive_number}: {len(corrupt_files)} corrupt images")
            for filename in corrupt_files[:5]:
                print(f"    - {filename}")
            if len(corrupt_files) > 5:
                print(f"    ... and {len(corrupt_files) - 5} more")

        print(f"\n{'='*80}")
        # EOF-safe (Windows trap registry: isatty() lies under hidden
        # consoles). The non-destructive branch is the fallback - an
        # unattended run must never delete the operator's imagery, and a
        # raw EOFError traceback here used to abort the summary too.
        if delete_corrupt == 'yes':
            response = 'yes'
        elif delete_corrupt == 'no':
            print("--delete-corrupt=no: leaving corrupt images in place.")
            response = 'no'
        else:
            try:
                response = input("\nDelete all corrupt images? (yes/no): ").strip().lower()
            except EOFError:
                print("Non-interactive run: NOT deleting anything. "
                      "Pass --delete-corrupt=yes to delete unattended.")
                response = 'no'

        if response == 'yes':
            deleted_count = 0
            failed_delete_count = 0

            print("\nDeleting corrupt images...")
            for corrupt_file in tqdm(all_corrupt_files, desc="Deleting"):
                try:
                    os.remove(corrupt_file['path'])
                    deleted_count += 1
                except Exception as e:
                    print(f"  Failed to delete {corrupt_file['filename']}: {e}")
                    failed_delete_count += 1

            print(f"\nSuccessfully deleted: {deleted_count} images")
            if failed_delete_count > 0:
                print(f"Failed to delete: {failed_delete_count} images")

            validation_stats['deleted'] = deleted_count
            validation_stats['failed_delete'] = failed_delete_count
        else:
            print("\nSkipping deletion. Corrupt images remain in output directories.")
            validation_stats['deleted'] = 0
            validation_stats['failed_delete'] = 0
    else:
        print("\nNo corrupt images found!")

    print(f"{'='*80}\n")
    return validation_stats


def generate_flight_log(matched_images: list[dict], dive_number: str, utm_zone: str | None,
                        output_dir: str, accuracies: dict | None = None,
                        declination_deg: float | None = None) -> str:
    """Generate a flight log file with position and orientation accuracy. Includes camera subfolder in image paths."""
    # Never emit a '_UNKNOWN_' tag into a *_UTM.txt name: it parses as "no
    # zone tag", which every downstream consumer reads as a LOCAL-frame
    # campaign (audit 2026-08-07). Same rule as the module's writer.
    if utm_zone:
        flight_log_filename = os.path.join(
            output_dir, f"flight_log_{dive_number}_{utm_zone}_UTM.txt")
    else:
        flight_log_filename = os.path.join(
            output_dir, f"flight_log_{dive_number}_UNRESOLVED.txt")
        print(f"ERROR: no UTM zone resolved for {dive_number} - writing "
              f"{os.path.basename(flight_log_filename)}, deliberately OUTSIDE "
              "the flight_log*_UTM.txt discovery glob so it cannot be "
              "mistaken for a local-frame log.")

    if os.path.exists(flight_log_filename):
        os.remove(flight_log_filename)

    # ONE accuracy table, shared with the georeference module
    # (PRIOR_ACCURACY_DEFAULTS). These were literals in both files, so the
    # two could - and did - disagree; --pos-accuracy/--alt-accuracy/
    # --orientation-accuracy override them per run (audit 2026-08-07).
    acc = dict(_ACCURACY_DEFAULTS)
    acc.update(accuracies or {})
    pos_x_acc = pos_y_acc = float(acc['pos_xy'])
    alt_acc = float(acc['alt'])
    yaw_acc = float(acc['yaw'])
    roll_acc = float(acc['roll'])
    # House convention for an UNMEASURED mount; a measured MOUNTS entry still
    # wins. Negative assumed pitch is the opt-out (no pitch prior at all).
    assumed_pitch = float(acc.get('assumed_pitch', _ASSUMED_MOUNT['pitch']))
    assumed_pitch_acc = float(
        acc.get('assumed_pitch_acc', _ASSUMED_MOUNT['p_acc']))
    assume_pitch = assumed_pitch >= 0.0
    decl = (MAGNETIC_DECLINATION_DEG if declination_deg is None
            else float(declination_deg))

    with open(flight_log_filename, "w") as f:
        f.write(
            "Name;X (East);Y (North);Alt;X Accuracy;Y Accuracy;Alt Accuracy;Yaw;Pitch;Roll;Yaw Accuracy;Pitch Accuracy;Roll Accuracy\n"
        )

        for image in matched_images:
            heading_mag = image.get("HEADING_MAG")
            pitch_vehicle = image.get("PITCH_VEHICLE")
            roll_vehicle = image.get("ROLL_VEHICLE")

            camera_pitch_offset = get_camera_pitch_offset(
                image["FILENAME"], assume_pitch=assume_pitch,
                pitch_deg=assumed_pitch, accuracy_deg=assumed_pitch_acc)
            rc_yaw, rc_pitch, rc_roll = convert_to_rc_orientation(
                heading_mag, pitch_vehicle, roll_vehicle, camera_pitch_offset, decl
            )

            pitch_acc = get_camera_pitch_accuracy(
                image["FILENAME"], assume_pitch=assume_pitch,
                pitch_deg=assumed_pitch, accuracy_deg=assumed_pitch_acc)

            def fmt(val):
                return f"{val:.6f}" if val is not None else ""

            # Include camera subfolder in the image path for RealityScan
            image_path = f"{image['CAMERA_TYPE']}/{image['FILENAME']}"

            line = ";".join([
                image_path,
                fmt(image.get("UTM_X")),
                fmt(image.get("UTM_Y")),
                fmt(image.get("ALTITUDE_EST")),
                fmt(pos_x_acc),
                fmt(pos_y_acc),
                fmt(alt_acc),
                fmt(rc_yaw),
                fmt(rc_pitch),
                fmt(rc_roll),
                fmt(yaw_acc),
                fmt(pitch_acc),
                fmt(roll_acc)
            ])
            f.write(line + "\n")

    return flight_log_filename


def print_dive_summary(dive_number: str, csv_rows: int, examined: int, stats: dict,
                      flight_log_path: str, utm_zone: str | None, copied: int, failed: int,
                      camera_copy_counts: dict, image_dir: str):
    """Print comprehensive summary for a dive."""
    print(f"\n{'='*80}")
    print(f"DIVE SUMMARY: {dive_number}")
    print(f"{'='*80}")
    print(f"CSV Rows Loaded:          {csv_rows}")
    print(f"Images Examined:          {examined}")
    print(f"Matched (<=2s):           {stats['matches_made']} ({100.0 * stats['matches_made'] / examined:.1f}%)" if examined > 0 else "Matched (<=2s):           0 (0.0%)")
    print(f"Rejected (>2s):           {stats['rejected_time']}")
    print(f"\nTime-Delta Buckets (all pairs, pre-threshold):")
    print(f"  Exact matches:          {stats['exact_matches']}")
    print(f"  0-4 seconds:            {stats['matches_0_4']}")
    print(f"  4-15 seconds:           {stats['matches_4_15']}")
    print(f"  >15 seconds:            {stats['matches_gt15']}")
    print(f"\nAccepted Field Completeness:")
    print(f"  Missing UTM:            {stats['accepted_missing_utm']}")
    print(f"  Missing Orientation:    {stats['accepted_missing_orientation']}")

    if camera_copy_counts:
        print(f"\nImage Copy Results:")
        print(f"  Successfully Copied:    {copied}")
        print(f"  Failed to Copy:         {failed}")
        print(f"\nImages Copied by Camera Type (organized in subdirectories):")
        for camera_type in sorted(camera_copy_counts.keys()):
            print(f"  {camera_type:15s}     {camera_copy_counts[camera_type]}")
        print(f"\n  Image Directory:        {image_dir}")
        print(f"  Organization:           Images organized by camera in subdirectories")

    print(f"\nUTM Zone:                 {utm_zone if utm_zone else 'UNKNOWN (no valid GPS data)'}")
    print(f"Flight Log:               {flight_log_path}")
    print(f"Lines Written:            {stats['matches_made']}")
    print(f"{'='*80}\n")


def build_arg_parser() -> "argparse.ArgumentParser":
    """CLI front end (added 2026-08-07).

    geoall used to ignore argv entirely and prompt unconditionally, so it
    could not be run unattended and `geoall.py --help` was an EOFError
    traceback - while the docs call it the canonical georeferencer. Every
    flag routes through SettingsStore.ask (CLI value wins, is persisted,
    and an unattended run silently takes the stored value), matching
    run_models/finish_model conventions.
    """
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[1])
    p.add_argument('--image-base-dir', default=None,
                   help="image base directory (contains 'edt' subdirectories)")
    p.add_argument('--rov-data-dir', default=None,
                   help='ROV data directory (dive datatable CSVs)')
    p.add_argument('--output-dir', default=None,
                   help='output directory (flight logs and copied images)')
    p.add_argument('--declination', type=float, default=None,
                   help='magnetic declination at the site in degrees, east '
                        'positive (default 0 = nav heading treated as true '
                        'north)')
    p.add_argument('--pos-accuracy', type=float, default=None,
                   help='X/Y position accuracy claimed for every image, in '
                        'metres (default %.1f)' % _ACCURACY_DEFAULTS['pos_xy'])
    p.add_argument('--alt-accuracy', type=float, default=None,
                   help='altitude accuracy claimed for every image, in metres '
                        '(default %.1f)' % _ACCURACY_DEFAULTS['alt'])
    p.add_argument('--assumed-pitch', type=float, default=None,
                   help='down-tilt assumed for a camera family with NO '
                        'measured mount, in degrees below the vehicle forward '
                        'axis (default %.1f; negative writes no pitch prior '
                        'at all). A measured mount always wins.'
                        % _ASSUMED_MOUNT['pitch'])
    p.add_argument('--assumed-pitch-accuracy', type=float, default=None,
                   help='accuracy claimed for that assumed tilt in degrees '
                        '(default %.1f - no tighter than the loosest MEASURED '
                        'mount, because the geometry is assumed)'
                        % _ASSUMED_MOUNT['p_acc'])
    p.add_argument('--orientation-accuracy', type=float, default=None,
                   help='yaw/roll accuracy claimed for every image, in '
                        'degrees (default %.1f; 3-5 fragments the solve, '
                        'PD-0)' % _ACCURACY_DEFAULTS['yaw'])
    p.add_argument('--delete-corrupt', choices=('ask', 'yes', 'no'),
                   default='ask',
                   help="what to do with corrupt images found during "
                        "validation; unattended runs always behave as 'no'")
    return p


def main(argv: list[str] | None = None):
    """Main execution function."""
    args = build_arg_parser().parse_args(argv)
    settings = SettingsStore()
    image_base_dir = settings.ask(
        "geoall", "image_base_dir", args.image_base_dir,
        DEFAULT_IMAGE_BASE_DIR)
    rov_data_dir = settings.ask(
        "geoall", "rov_data_dir", args.rov_data_dir, DEFAULT_ROV_DATA_DIR)
    output_dir = settings.ask(
        "geoall", "output_dir", args.output_dir, DEFAULT_OUTPUT_DIR)
    declination = float(settings.ask(
        "geoall", "declination_deg", args.declination,
        MAGNETIC_DECLINATION_DEG))
    accuracies = {
        'pos_xy': float(settings.ask("geoall", "pos_accuracy_m",
                                     args.pos_accuracy,
                                     _ACCURACY_DEFAULTS['pos_xy'])),
        'alt': float(settings.ask("geoall", "alt_accuracy_m",
                                  args.alt_accuracy,
                                  _ACCURACY_DEFAULTS['alt'])),
        'yaw': float(settings.ask("geoall", "orientation_accuracy_deg",
                                  args.orientation_accuracy,
                                  _ACCURACY_DEFAULTS['yaw'])),
        'assumed_pitch': float(settings.ask(
            "geoall", "assumed_pitch_deg", args.assumed_pitch,
            _ASSUMED_MOUNT['pitch'])),
        'assumed_pitch_acc': float(settings.ask(
            "geoall", "assumed_pitch_accuracy_deg",
            args.assumed_pitch_accuracy, _ASSUMED_MOUNT['p_acc'])),
    }
    accuracies['roll'] = accuracies['yaw']

    print("="*80)
    print("GEOREFERENCE IMAGES - MULTI-DIVE PROCESSOR (OPTIMIZED)")
    print("="*80)
    print(f"Image Base Directory:  {image_base_dir}")
    print(f"ROV Data Directory:    {rov_data_dir}")
    print(f"Output Directory:      {output_dir}")
    print(f"Match Threshold:       {MATCH_THRESHOLD_SEC} seconds")
    # ASCII only in console output (Windows cp1252 consoles crash on non-ASCII).
    print(f"Magnetic Declination:  {declination} deg")
    print(f"Prior Accuracies:      pos {accuracies['pos_xy']} m, "
          f"alt {accuracies['alt']} m, orientation {accuracies['yaw']} deg")
    if accuracies['assumed_pitch'] >= 0.0:
        print(f"Assumed mount:         {accuracies['assumed_pitch']} deg down "
              f"at {accuracies['assumed_pitch_acc']} deg accuracy, for "
              "families with NO measured mount (a measured one always wins)")
    else:
        print("Assumed mount:         DISABLED - a family with no measured "
              "mount gets no pitch prior at all")
    print(f"Worker Processes:      {NUM_WORKERS}")
    print("="*80)
    print("Features:")
    print("  - Images organized by camera type in subdirectories")
    print("  - Binary search for timestamp matching")
    print("  - Parallel file copying")
    print("  - Parallel image validation")
    print("  - Pre-compiled regex patterns")
    print("="*80)

    print("\nSearching for 'edt' subdirectories...")
    edt_dirs = find_all_edt_directories(image_base_dir)
    print(f"Found {len(edt_dirs)} edt directories")

    if not edt_dirs:
        print("Error: No 'edt' subdirectories found!")
        return

    print("\nSearching for ROV datafiles...")
    dive_files = find_rov_datafiles(rov_data_dir)
    print(f"Found {len(dive_files)} dive datafiles:")
    for dive_num in sorted(dive_files.keys()):
        print(f"  {dive_num}: {os.path.basename(dive_files[dive_num])}")

    if not dive_files:
        print("Error: No ROV datafiles found!")
        return

    all_images = read_image_filenames(edt_dirs)

    if not all_images:
        print("Error: No valid images with timestamps found!")
        return

    print(f"\nSample image timestamps (first 5):")
    for img in all_images[:5]:
        print(f"  {img['FILENAME']}: {img['TIMESTAMP']}")

    overall_stats = {
        'total_dives': len(dive_files),
        'total_images_processed': 0,
        'total_matches': 0,
        'total_copied': 0,
        'total_failed_copy': 0,
        'overall_camera_counts': defaultdict(int)
    }

    processed_dives = []

    for dive_number, csv_path in sorted(dive_files.items()):
        print(f"\n{'#'*80}")
        print(f"PROCESSING DIVE: {dive_number}")
        print(f"{'#'*80}")

        try:
            print(f"Loading CSV: {os.path.basename(csv_path)}")
            data_rows = read_csv_data(csv_path)
            print(f"  Loaded {len(data_rows)} data rows")

            if data_rows:
                print(f"  CSV time range: {data_rows[0]['TIME']} to {data_rows[-1]['TIME']}")

            utm_zone_cache = {}
            matched_images, stats = estimate_location(all_images, data_rows, utm_zone_cache)

            utm_zone = utm_zone_cache.get('zone')

            if matched_images:
                copied_count, failed_count, camera_copy_counts = copy_matched_images(matched_images, dive_number, output_dir)

                flight_log_path = generate_flight_log(
                    matched_images, dive_number, utm_zone, output_dir,
                    accuracies=accuracies, declination_deg=declination)
                if utm_zone_cache.get('crossings'):
                    print(f"WARNING: {utm_zone_cache['crossings']} nav row(s) "
                          f"lie outside pinned UTM zone {utm_zone} and were "
                          "projected into it anyway - confirm the survey "
                          "really spans a zone boundary.")

                overall_stats['total_matches'] += stats['matches_made']
                overall_stats['total_copied'] += copied_count
                overall_stats['total_failed_copy'] += failed_count

                for camera_type, count in camera_copy_counts.items():
                    overall_stats['overall_camera_counts'][camera_type] += count

                dive_image_dir = os.path.join(output_dir, dive_number)
                print_dive_summary(dive_number, len(data_rows), len(all_images), stats,
                                 flight_log_path, utm_zone, copied_count, failed_count,
                                 camera_copy_counts, dive_image_dir)

                processed_dives.append(dive_number)
            else:
                print(f"\nNo images matched for dive {dive_number}")
                dive_image_dir = os.path.join(output_dir, dive_number)
                print_dive_summary(dive_number, len(data_rows), len(all_images), stats,
                                 "N/A", utm_zone, 0, 0, {}, dive_image_dir)

            overall_stats['total_images_processed'] += len(all_images)

        except Exception as e:
            print(f"Error processing dive {dive_number}: {e}")
            traceback.print_exc()
            continue

    print(f"\n{'='*80}")
    print("OVERALL SUMMARY")
    print(f"{'='*80}")
    print(f"Total Dives Processed:         {overall_stats['total_dives']}")
    print(f"Total Images Examined:         {len(all_images)}")
    print(f"Total Matches Across All Dives: {overall_stats['total_matches']}")
    print(f"Total Images Copied:           {overall_stats['total_copied']}")
    print(f"Total Copy Failures:           {overall_stats['total_failed_copy']}")

    if overall_stats['overall_camera_counts']:
        print(f"\nTotal Images Copied by Camera Type:")
        for camera_type in sorted(overall_stats['overall_camera_counts'].keys()):
            print(f"  {camera_type:15s}     {overall_stats['overall_camera_counts'][camera_type]}")

    print(f"\nOutput Directory:              {output_dir}")
    print(f"Image Organization:            By dive, then by camera type in subdirectories")
    print(f"Flight Log Format:             Includes camera subfolder paths (e.g., CamUpper/image.jpg)")
    print(f"{'='*80}\n")

    if processed_dives and overall_stats['total_copied'] > 0:
        validation_stats = validate_and_cleanup_images(
            output_dir, processed_dives, delete_corrupt=args.delete_corrupt)

        if validation_stats.get('deleted', 0) > 0:
            print(f"\nFinal image count after cleanup: {overall_stats['total_copied'] - validation_stats['deleted']}")

    print("Processing complete!")


if __name__ == "__main__":
    main()