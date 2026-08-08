from __future__ import annotations

import bisect
import csv
import math
import os
from datetime import datetime

import utm
from PIL import Image

from ..file_metadata_parser import parse_timestamp
from .. import camera_registry
from .. import image_exts


from module_base.rs_module import RSModule
from module_base.parameter import Parameter


# Mount geometry per FILENAME FAMILY (camera_registry.family), NOT per physical
# camera. The same Cinema unit sits 10 deg down under legacy 'camlower' names and
# 45 deg down under WCA 'C###C' names, so keying this off the camera would
# silently change every legacy dataset by tens of degrees.
#
#   fwd  : + ahead of the vehicle reference point (m)
#   lat  : + to the right (m; zero for every known mount)
#   down : + below the reference point (m)
#   pitch: camera down-tilt from the vehicle forward axis (deg)
#   p_acc: claimed accuracy of that pitch prior (deg)
#
# These are the values in force on 2026-07-26, pinned by
# testing/test_rig_mounts.py so the table cannot drift unnoticed.
# superseded-by modules/cameras.json families[].mount - pending migration step (c+)
MOUNTS: dict[str, dict | None] = {
    'zeuss': {'fwd': 0.5, 'lat': 0.0, 'down': 0.5, 'pitch': 30.0, 'p_acc': 30.0},
    'legacy_camupper': {'fwd': 1.0, 'lat': 0.0, 'down': 0.0, 'pitch': 70.0, 'p_acc': 10.0},
    'legacy_cammid': {'fwd': 1.0, 'lat': 0.0, 'down': 1.0, 'pitch': 20.0, 'p_acc': 10.0},
    'legacy_camlower': {'fwd': 1.0, 'lat': 0.0, 'down': 1.0, 'pitch': 10.0, 'p_acc': 5.0},
    # WCA Port/Cinema lever arms are VALIDATED on two independent metrically
    # sound solves (bow c2, zone_2/PD-2b): C above P by +1.12 m and +1.03 m
    # against the +1.00 m implied here. Do NOT flatten them to equal height on
    # the strength of the 0.22 m / 0.00 m figures in FINDINGS - those came from
    # the 0.175-scale hull and are scale-corrupted (retracted 2026-07-25, then
    # briefly re-applied 2026-07-26 until a contradiction audit caught it).
    # Pitch accuracy is 15 deg, not 3-5: tighter FRAGMENTS the solve (PD-0).
    'wca_port': {'fwd': 1.0, 'lat': 0.0, 'down': 1.0, 'pitch': 0.0, 'p_acc': 15.0},
    'wca_cinema': {'fwd': 1.0, 'lat': 0.0, 'down': 0.0, 'pitch': 45.0, 'p_acc': 15.0},
    # Starboard's mount has NEVER been measured. The owner excludes Starboard
    # from photogrammetry, so this should not be reached - and if it is, the run
    # must SAY SO rather than invent a zero lever arm and a 0 deg tilt.
    # Inventing rig numbers is what produced the Port-1 m incident.
    'wca_starboard': None,
}


# End-to-end PER-IMAGE uncertainty written into every flight-log row, NOT
# the sensor spec. The rig's DVL (~1 m XY) and Paro depth (~0.1 m Z)
# describe instantaneous sensor precision; the number RealityScan wants
# also absorbs timestamp matching, nav interpolation, lever arm, and
# dive-long drift. Claiming the sensor figure (1/1/0.1) measurably
# FRAGMENTS solves: on the known-good bow fixture, loose gave ONE
# component at scale ~1.0 under both distortion models, while tight split
# it into 2-3 and pushed the maximal component's scale further from truth
# (0.886 / 0.826). See testing/PRIORS_DISTORTION_TEST_PLAN.md "bow 2x2".
# An intermediate ladder (3/3/0.5 etc.) is untested - queued, and now
# REACHABLE: these are the defaults of real parameters/flags rather than
# function locals in two files (audit 2026-08-07 - step 6 of the owner's
# chain, "calculation/use of uncertainty", had no knob anywhere).
#
# Orientation: HONEST 15 deg until the camera mounts are ground-truthed
# (PD-0/PD-0b dose-response, 2026-07-25: 3-5 deg claimed accuracy
# FRAGMENTS the solve, 15 deg gains registration; see the
# PRIORS_DISTORTION_TEST_PLAN orientation-frame caveat). Pitch accuracy is
# per-mount (MOUNTS[...]['p_acc']) and is deliberately NOT listed here.
#
# ONE table, shared by modules/georeference and geoall.py (which already
# imports MOUNTS from here) so the two implementations cannot drift apart
# again the way the 3-vs-15 orientation accuracy did.
# superseded-by modules/cameras.json defaults - pending migration step (c+)
PRIOR_ACCURACY_DEFAULTS: dict[str, float] = {
    'pos_xy': 10.0,   # X and Y accuracy, metres
    'alt': 1.0,       # Alt accuracy, metres
    'yaw': 15.0,      # Yaw accuracy, degrees
    'roll': 15.0,     # Roll accuracy, degrees
}


class GeoreferenceImages(RSModule):
    TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
    # superseded-by modules/cameras.json families[].timestamp_formats - pending migration step (c+)
    WCA_FILENAME_TIMESTAMP_FORMAT = "%Y%m%d%H%M%S"
    ZEUSS_FILENAME_TIMESTAMP_FORMAT = "%Y%m%d%H%M%S"
    WCA2025_FILENAME_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"

    def __init__(self, logger):
        super().__init__("Georeference Images", logger)
        self.utm_zone = None
        self.stats: dict[str, int | float] = {}
        # Unknown-camera warnings fire once per run (a dataset with an
        # unrecognized naming scheme would otherwise emit one per image)
        self._unknown_camera_example: str | None = None
        self._unknown_camera_count = 0
        # UTM zone pinning: the first converted row fixes the zone for the
        # whole cruise; later rows whose natural zone differs are counted.
        self._utm_force: tuple[int, str] | None = None
        self._utm_crossings = 0
        self._utm_crossing_example: tuple[float, float, int] | None = None
        # Images whose mount geometry is unknown get NO invented tilt.
        self._no_mount_stems: set[str] = set()

    def _note_unknown_camera(self, filename: str, context: str) -> None:
        self._unknown_camera_count += 1
        if self._unknown_camera_example is None:
            self._unknown_camera_example = filename
            self.logger.warning(
                f"Unknown camera type (e.g. '{filename}'): {context}. "
                "Further unknown-camera warnings are suppressed; the total "
                "is reported in the run summary.")

    def get_parameters(self) -> dict[str, Parameter]:
        additional_params = {}

        additional_params['geo_input_image_dir'] = Parameter(
            name='Input Image Folder',
            cli_short='g_i',
            cli_long='g_input',
            type=str,
            default_value=None,
            description='Directory containing the images to georeference',
            prompt_user=True,
            disable_when_module_active='Extract Images'
        )

        additional_params['geo_input_flight_log'] = Parameter(
            name='Input Flight Log',
            cli_short='g_f',
            cli_long='g_flight_log',
            type=str,
            default_value=None,
            description='Path to the ROV output GPS data file',
            prompt_user=True
        )

        additional_params['geo_input_type'] = Parameter(
            name='Input Data Type',
            cli_short='g_t',
            cli_long='g_type',
            type=str,
            default_value=None,
            description='Type of data to process (Zeuss, WCA, WCA2025, or All)',
            prompt_user=True
        )

        # prompt_user=True (audit 2026-08-07): declination is a named
        # trajectory variable of the owner's chain, and with prompt_user
        # False neither main.py nor the wildscan portal ever asked for it -
        # the only way to set it was the -g_d flag, so a site with real
        # declination silently got true-north yaw equal to magnetic yaw.
        additional_params['magnetic_declination_deg'] = Parameter(
            name='Magnetic Declination (deg)',
            cli_short='g_d',
            cli_long='g_declination',
            type=float,
            default_value=0.0,
            description='Magnetic declination at the site in degrees, east '
                        'positive (0 = treat the nav heading as true north)',
            prompt_user=True
        )

        # Step 6 of the owner's chain - "calculation/use of uncertainty".
        # These were function locals in TWO files with no flag, no prompt
        # and no settings key; tuning them meant editing source
        # (audit 2026-08-07). Defaults + provenance: PRIOR_ACCURACY_DEFAULTS.
        additional_params['geo_pos_accuracy_m'] = Parameter(
            name='Position Accuracy (m)',
            cli_short='g_pa',
            cli_long='g_pos_accuracy',
            type=float,
            default_value=PRIOR_ACCURACY_DEFAULTS['pos_xy'],
            description='X/Y position accuracy claimed for every image, in '
                        'metres (end-to-end uncertainty, NOT the DVL spec - '
                        'tightening it fragments solves, PD-0)',
            prompt_user=True
        )

        additional_params['geo_alt_accuracy_m'] = Parameter(
            name='Altitude Accuracy (m)',
            cli_short='g_aa',
            cli_long='g_alt_accuracy',
            type=float,
            default_value=PRIOR_ACCURACY_DEFAULTS['alt'],
            description='Altitude accuracy claimed for every image, in metres',
            prompt_user=True
        )

        additional_params['geo_orientation_accuracy_deg'] = Parameter(
            name='Orientation Accuracy (deg)',
            cli_short='g_oa',
            cli_long='g_orientation_accuracy',
            type=float,
            default_value=PRIOR_ACCURACY_DEFAULTS['yaw'],
            description='Yaw/roll accuracy claimed for every image, in '
                        'degrees (15 = honest until the mounts are '
                        'ground-truthed; 3-5 fragments the solve, PD-0)',
            prompt_user=True
        )

        additional_params['geo_min_accept_rate_pct'] = Parameter(
            name='Minimum Acceptance Rate (%)',
            cli_short='g_mr',
            cli_long='g_min_accept_rate',
            type=float,
            default_value=80.0,
            description='Fail the run when fewer than this percent of images '
                        'match the nav table within 2 s (0 disables the '
                        'floor; a partial match silently georeferences only '
                        'part of the dive)',
            prompt_user=True
        )

        return {**super().get_parameters(), **additional_params}

    def _accuracy(self, param_name: str, key: str) -> float:
        """A prior-accuracy parameter's value, or its shared default when
        the parameter is absent (direct instantiation in tests/drivers)."""
        param = (self.params or {}).get(param_name)
        value = None if param is None else param.get_value()
        return float(PRIOR_ACCURACY_DEFAULTS[key] if value is None else value)

    @staticmethod
    def _wrap360(angle_deg: float) -> float:
        """Wrap angle to [0, 360) range."""
        return angle_deg % 360.0

    def _mount_for(self, filename: str) -> dict | None:
        """Mount geometry for an image, or None when it is not known.

        ONE resolution point for all three priors, so an image can never take a
        lever arm from one table and a pitch from another. Unknown families and
        known-but-unmeasured mounts are both reported once, via the existing
        unknown-camera counter, so the run summary carries a single number for
        "images that got no usable prior".
        """
        fam = camera_registry.family(filename)
        mount = MOUNTS.get(fam) if fam else None
        if mount is None:
            if fam is None:
                self._note_unknown_camera(
                    filename, 'no camera family matches it, so it gets NO '
                    'position or orientation prior - add its prefix to '
                    'camera_registry.family() before trusting this run')
            else:
                self._note_unknown_camera(
                    filename, f'family "{fam}" has NO measured mount geometry, '
                    'so it gets no position or orientation prior - measure the '
                    'mount or exclude the camera, do not guess')
        return mount

    def _get_camera_offsets(self, filename: str) -> tuple[float, float, float]:
        """(forward, lateral, down) lever arm in metres; zeros when unknown."""
        mount = self._mount_for(filename)
        if mount is None:
            return (0.0, 0.0, 0.0)
        return (mount['fwd'], mount['lat'], mount['down'])

    def _get_camera_pitch_offset(self, filename: str) -> float | None:
        """Camera down-tilt from the vehicle forward axis, in degrees, or
        None when the mount has never been measured.

        None means NO PITCH PRIOR - __generate_flight_log writes empty
        Pitch and Pitch Accuracy fields for that image. It used to return
        0.0, i.e. "this camera looks straight ahead", asserted at 10 deg
        confidence (see _get_camera_pitch_accuracy) on a mount nobody ever
        measured - exactly what the MOUNTS['wca_starboard'] = None comment
        forbids, and the failure mode PD-0 showed FRAGMENTS solves
        (audit 2026-08-07). Yaw and roll come from the nav table, not the
        mount, so they are still written.
        """
        mount = self._mount_for(filename)
        if mount is None:
            self._no_mount_stems.add(filename)
            return None
        return mount['pitch']

    def _get_camera_pitch_accuracy(self, filename: str) -> float | None:
        """Claimed accuracy of the pitch prior in degrees, or None when
        there is no pitch prior to claim an accuracy for."""
        mount = self._mount_for(filename)
        return None if mount is None else mount['p_acc']

    def _apply_camera_position_offset(self, utm_x: float | None, utm_y: float | None,
                                      altitude: float | None, heading_deg: float | None,
                                      forward_m: float, lateral_m: float, down_m: float) -> tuple[
        float | None, float | None, float | None]:
        """
        Apply camera position offset from vehicle center to world coordinates.

        Args:
            utm_x, utm_y: Vehicle position in UTM
            altitude: Vehicle altitude (negative depth)
            heading_deg: Vehicle heading in degrees (0=North, 90=East, clockwise)
            forward_m: Camera offset forward from vehicle center
            lateral_m: Camera offset to right from vehicle center
            down_m: Camera offset down from vehicle center

        Returns:
            (adjusted_utm_x, adjusted_utm_y, adjusted_altitude)
        """
        if utm_x is None or utm_y is None or heading_deg is None:
            return utm_x, utm_y, altitude

        # Convert heading to radians for trig functions
        heading_rad = math.radians(heading_deg)

        # Transform offsets from vehicle frame to world frame
        # In UTM: X=East, Y=North
        # Vehicle frame: forward along heading, right perpendicular to heading
        # Heading 0°=North, 90°=East (clockwise from North)

        # Forward offset contribution:
        # - East component: forward * sin(heading)
        # - North component: forward * cos(heading)
        east_offset = forward_m * math.sin(heading_rad)
        north_offset = forward_m * math.cos(heading_rad)

        # Lateral offset contribution (right side of vehicle):
        # - East component: lateral * cos(heading)
        # - North component: lateral * -sin(heading)
        east_offset += lateral_m * math.cos(heading_rad)
        north_offset += lateral_m * (-math.sin(heading_rad))

        # Apply offsets
        adjusted_utm_x = utm_x + east_offset
        adjusted_utm_y = utm_y + north_offset

        # Altitude offset (down is negative altitude)
        adjusted_altitude = altitude - down_m if altitude is not None else None

        return adjusted_utm_x, adjusted_utm_y, adjusted_altitude

    def _convert_to_rc_orientation(self, heading_mag: float | None, pitch_vehicle: float | None,
                                   roll_vehicle: float | None, camera_offset: float,
                                   decl_deg: float) -> tuple[float | None, float | None, float | None]:
        """
        Convert vehicle orientation to RealityScan conventions.

        Input conventions:
        - heading_mag: magnetic heading, 0=North, 90=East, 180=South, 270=West (clockwise)
        - pitch_vehicle: vehicle pitch from horizontal, negative=nose down
        - roll_vehicle: vehicle roll, negative=left wing down, positive=right wing down
        - camera_offset: camera down angle from vehicle (positive = down)

        RealityScan conventions (standard aerial photogrammetry):
        - Yaw: 0=North, 90=East, 180=South, 270=West
        - Pitch: 0=nadir (straight down), 90=horizontal, -90=straight up
        - Roll: 0=level, positive=right wing down
        """
        # Yaw: Convert magnetic heading to true north, then use directly as RC yaw
        if heading_mag is not None:
            true_heading = heading_mag + decl_deg
            rc_yaw = self._wrap360(true_heading)
        else:
            rc_yaw = None

        # Pitch: Convert vehicle pitch and camera offset to RC pitch
        # RC pitch: 0=nadir, 90=horizontal
        # Camera pitch from horizontal = vehicle_pitch - camera_offset
        # RC pitch = 90 + camera_pitch_from_horizontal
        # camera_offset None = no measured mount = no pitch prior at all.
        if pitch_vehicle is not None and camera_offset is not None:
            camera_pitch_from_horiz = pitch_vehicle - camera_offset
            rc_pitch = 90.0 + camera_pitch_from_horiz
        else:
            rc_pitch = None

        # Roll: Pass through directly (same convention)
        rc_roll = roll_vehicle

        return rc_yaw, rc_pitch, rc_roll

    def __read_csv_data(self, filename):
        """Read and parse CSV data from a file, including sensor and position data."""
        data_rows = []
        try:
            with open(filename, "r") as csvfile:
                reader = csv.reader(csvfile, delimiter=',')
                header = next(reader)
                idx_map = {name: index for index, name in enumerate(header)}
                for row in reader:
                    data_rows.append({
                        "TIME": datetime.strptime(row[idx_map['Timestamp']], self.TIMESTAMP_FORMAT),
                        "LAT": float(row[idx_map['kalman_lat']]) if row[idx_map['kalman_lat']] else None,
                        "LONG": float(row[idx_map['kalman_long']]) if row[idx_map['kalman_long']] else None,
                        "DEPTH": -abs(float(row[idx_map['kalman_depth']])) if row[idx_map['kalman_depth']] else None,
                        "HEADING_MAG": float(row[idx_map['kalman_yaw_deg']]) if row[
                            idx_map['kalman_yaw_deg']] else None,
                        "PITCH": float(row[idx_map['kalman_pitch_deg']]) if row[idx_map['kalman_pitch_deg']] else None,
                        "ROLL": float(row[idx_map['kalman_roll_deg']]) if row[idx_map['kalman_roll_deg']] else None
                    })
            self.stats['csv_rows'] = len(data_rows)
        except Exception as e:
            self.logger.error(f"Error processing CSV file: {e}")
            raise e
        return data_rows

    def __convert_to_utm(self, lat, lon):
        """Convert latitude and longitude to UTM, PINNED to the first row's
        zone.

        The zone used to latch on the first converted row while every later
        row was still converted in ITS OWN natural zone - so a track
        crossing a zone boundary got a silent ~500 km easting discontinuity
        (and an equator crossing ~9,900 km of northing) inside a log whose
        filename claimed one zone (audit 2026-08-07). force_zone_* keeps
        one continuous coordinate frame, which is what the single CRS XML
        derived from that filename actually declares; crossings are
        reported once, with a count, at the end of the run.
        """
        if lat is None or lon is None:
            return None, None
        try:
            if self._utm_force is None:
                easting, northing, zone_number, zone_letter = \
                    utm.from_latlon(lat, lon)
                self._utm_force = (zone_number, zone_letter)
                self.utm_zone = f"{zone_number}{zone_letter}"
                return easting, northing
            zone_number, zone_letter = self._utm_force
            natural = utm.latlon_to_zone_number(lat, lon)
            if natural != zone_number:
                self._utm_crossings += 1
                if self._utm_crossing_example is None:
                    self._utm_crossing_example = (lat, lon, natural)
            easting, northing = utm.from_latlon(
                lat, lon, force_zone_number=zone_number,
                force_zone_letter=zone_letter)[:2]
            return easting, northing
        except Exception as e:
            self.logger.error(f"Failed to convert to UTM coordinates: {e}")
            return None, None

    def __is_image_file(self, filename, image_folder):
        """Header-only structural check. A full .verify() walks every byte
        for the CRCs - roughly 720 GB of reads on a dive of 18k 39MB
        stills - while opening the header rejects non-images in
        milliseconds. Deep corruption still surfaces at preprocessing/
        alignment, where the pixels are read anyway."""
        try:
            with Image.open(os.path.join(image_folder, filename)) as im:
                width, height = im.size
            return width > 0 and height > 0
        except Exception:
            return False

    def __parse_timestamp_from_filename(self, filename, data_type):
        """Extract and parse the timestamp from an image filename."""
        if data_type == "All":
            try:
                base_name = os.path.splitext(filename)[0]
                timestamp_part = base_name.split('_')[1]
                return datetime.strptime(timestamp_part, self.WCA2025_FILENAME_TIMESTAMP_FORMAT)
            except (IndexError, ValueError):
                pass

            timestamp = parse_timestamp(filename)
            if timestamp is not None and timestamp != datetime(1970, 1, 1, 0, 0, 0):
                return timestamp

            self.logger.error(f"Error parsing timestamp in filename: {filename}")
            return None

        elif data_type == "WCA2025":
            try:
                base_name = os.path.splitext(filename)[0]
                timestamp_part = base_name.split('_')[1]
                return datetime.strptime(timestamp_part, self.WCA2025_FILENAME_TIMESTAMP_FORMAT)
            except (IndexError, ValueError) as e:
                self.logger.error(f"Error parsing WCA2025 timestamp in filename: {filename} - {e}")
                return None
        else:
            timestamp = parse_timestamp(filename)
            if timestamp is None or timestamp == datetime(1970, 1, 1, 0, 0, 0):
                self.logger.error(f"Error parsing timestamp in filename: {filename}")
                return None
            return timestamp

    # What this stage can timestamp + open today. Deliberately narrower
    # than modules.image_exts.ALL_IMAGE_EXTS; the difference is REPORTED
    # below rather than filtered in silence (audit 2026-08-07).
    ACCEPTED_EXTENSIONS = frozenset({'.jpg', '.jpeg', '.png'})

    def __read_image_filenames(self, image_folder, data_type):
        """Read all image filenames from a folder and subdirectories, extracting their timestamps."""
        image_data = []
        image_extensions = self.ACCEPTED_EXTENSIONS

        jpeg_files = []
        all_names = []
        for root, dirs, files in os.walk(image_folder):
            for filename in files:
                all_names.append(filename)
                if os.path.splitext(filename.lower())[1] in image_extensions:
                    rel_path = os.path.relpath(os.path.join(root, filename), image_folder)
                    jpeg_files.append(rel_path)

        # A .tif/.heif dataset used to be simply invisible here while the
        # workspace census counted it - "extract done, 2 images" against
        # "georeferenced 1". Say what is being skipped.
        skipped = image_exts.skipped_by_extension(all_names, image_extensions)
        if skipped:
            self.logger.warning(
                'Skipping %d recognised image(s) this stage cannot process: '
                '%s. Only %s are georeferenced - convert them or they will '
                'have no priors.',
                sum(skipped.values()),
                ', '.join(f'{n} x {e}' for e, n in sorted(skipped.items())),
                ', '.join(sorted(image_extensions)))
            self.stats['files_skipped_by_extension'] = sum(skipped.values())

        total_files = len(jpeg_files)
        unreadable_files = 0
        ts_parse_failures = 0

        bar = self._initialize_loading_bar(total_files, "Reading Image Data")
        for rel_path in jpeg_files:
            full_path = os.path.join(image_folder, rel_path)
            filename = os.path.basename(rel_path)

            if self.__is_image_file(filename, os.path.dirname(full_path)):
                timestamp = self.__parse_timestamp_from_filename(filename, data_type)
                if timestamp:
                    image_data.append({"FILENAME": filename, "TIMESTAMP": timestamp})
                else:
                    ts_parse_failures += 1
            else:
                unreadable_files += 1
            self._update_loading_bar(bar, 1)

        self.stats['files_listed'] = total_files
        self.stats['files_unreadable'] = unreadable_files
        self.stats['timestamp_parse_failures'] = ts_parse_failures
        self.stats['images_with_valid_ts'] = len(image_data)

        return image_data

    @staticmethod
    def _find_closest_row_index(times: list[datetime], target_time: datetime) -> int:
        """Binary search for the index of the closest timestamp in a sorted
        list. Assumes times is sorted ascending."""
        idx = bisect.bisect_left(times, target_time)
        if idx == 0:
            return 0
        if idx == len(times):
            return len(times) - 1
        before, after = times[idx - 1], times[idx]
        if abs(target_time - before) <= abs(target_time - after):
            return idx - 1
        return idx

    def __estimate_location(self, image_data, data_rows, input_type) -> int:
        """Estimate location and orientation for each image. Accept only matches within 2 seconds."""
        MATCH_THRESHOLD_SEC = 2.0

        matches_made = 0
        exact_matches = 0
        matches_0_4 = 0
        matches_4_15 = 0
        matches_gt15 = 0
        rejected_time = 0
        rejected_no_csv = 0
        accepted_missing_utm = 0
        accepted_missing_orientation = 0

        # Sort once and binary-search per image instead of a linear scan
        # over the whole nav table per image (O(N log M) vs O(N*M))
        data_rows = sorted(data_rows, key=lambda row: row["TIME"])
        times = [row["TIME"] for row in data_rows]

        bar = self._initialize_loading_bar(len(image_data), "Estimating Location")
        for image in image_data:
            filename = image["FILENAME"]
            image["ACCEPTED"] = False

            if data_rows:
                closest_match = data_rows[self._find_closest_row_index(times, image["TIMESTAMP"])]
                time_diff = abs(closest_match["TIME"] - image["TIMESTAMP"])
                diff_sec = time_diff.total_seconds()

                # Contiguous buckets: the old ==0 / 1-4 / 5-15 / >15 split
                # silently dropped deltas in (0,1) and (4,5)
                if diff_sec == 0:
                    exact_matches += 1
                elif diff_sec <= 4:
                    matches_0_4 += 1
                elif diff_sec <= 15:
                    matches_4_15 += 1
                else:
                    matches_gt15 += 1

                if diff_sec > MATCH_THRESHOLD_SEC:
                    rejected_time += 1
                    self._update_loading_bar(bar, 1)
                    continue

                lat, lon = closest_match.get("LAT"), closest_match.get("LONG")
                utm_x, utm_y = self.__convert_to_utm(lat, lon)

                # Get camera position offsets
                forward_m, lateral_m, down_m = self._get_camera_offsets(filename)

                # Apply position offsets to get camera location
                camera_utm_x, camera_utm_y, camera_alt = self._apply_camera_position_offset(
                    utm_x, utm_y, closest_match.get("DEPTH"),
                    closest_match.get("HEADING_MAG"),
                    forward_m, lateral_m, down_m
                )

                image.update({
                    "LAT": lat,
                    "LONG": lon,
                    "UTM_X": camera_utm_x,
                    "UTM_Y": camera_utm_y,
                    "ALTITUDE_EST": camera_alt,
                    "HEADING_MAG": closest_match.get("HEADING_MAG"),
                    "PITCH_VEHICLE": closest_match.get("PITCH"),
                    "ROLL_VEHICLE": closest_match.get("ROLL"),
                    "ACCEPTED": True
                })
                matches_made += 1

                if camera_utm_x is None or camera_utm_y is None:
                    accepted_missing_utm += 1

                if (closest_match.get("HEADING_MAG") is None or
                        closest_match.get("PITCH") is None or
                        closest_match.get("ROLL") is None):
                    accepted_missing_orientation += 1

            else:
                rejected_no_csv += 1

            self._update_loading_bar(bar, 1)

        self.stats['examined_images'] = len(image_data)
        self.stats['accepted_images'] = matches_made
        self.stats['rejected_time'] = rejected_time
        self.stats['rejected_no_csv'] = rejected_no_csv
        self.stats['bucket_exact'] = exact_matches
        self.stats['bucket_0_4'] = matches_0_4
        self.stats['bucket_4_15'] = matches_4_15
        self.stats['bucket_gt15'] = matches_gt15
        self.stats['accepted_missing_utm'] = accepted_missing_utm
        self.stats['accepted_missing_orientation'] = accepted_missing_orientation
        self.stats['unknown_camera_images'] = self._unknown_camera_count
        total_rejected = rejected_time + rejected_no_csv
        self.stats['total_rejected'] = total_rejected
        self.stats['accept_rate_pct'] = (100.0 * matches_made / len(image_data)) if image_data else 0.0

        print("Matching summary:")
        print(f"  Examined images: {self.stats['examined_images']}")
        # ASCII only in console output: Windows cp1252 consoles (and
        # redirected stdout) crash on characters like U+2264.
        print(f"  Accepted <=2s:   {self.stats['accepted_images']} ({self.stats['accept_rate_pct']:.1f}%)")
        print(f"  Rejected >2s:    {self.stats['rejected_time']}")
        print(f"  Rejected no CSV: {self.stats['rejected_no_csv']}")
        print("  Time-delta buckets (all pairs, pre-threshold):")
        print(f"    Exact:  {self.stats['bucket_exact']}")
        print(f"    0-4s:   {self.stats['bucket_0_4']}")
        print(f"    4-15s:  {self.stats['bucket_4_15']}")
        print(f"    >15s:   {self.stats['bucket_gt15']}")
        print("  Accepted field completeness:")
        print(f"    Missing UTM:         {self.stats['accepted_missing_utm']}")
        print(f"    Missing orientation: {self.stats['accepted_missing_orientation']}")
        if self._unknown_camera_count:
            # _unknown_camera_count counts mount LOOKUPS (three per image),
            # not images; the per-image figure is printed by
            # __generate_flight_log as "Rows with NO pitch prior". Say which
            # is which rather than mislabelling a call counter as an image
            # count, and drop the stale "default accuracies used" claim -
            # an unmeasured mount now gets NO pitch prior at all.
            print(f"  Unmeasured-mount lookups: {self._unknown_camera_count} "
                  f"(e.g. {self._unknown_camera_example}) - zero lever arm, "
                  f"and NO pitch prior is written for those rows")

        return matches_made

    def __generate_flight_log(self, image_data, image_folder):
        """Generate a flight log file with position and orientation accuracy."""
        # NEVER emit a '_UNKNOWN_' tag into a *_UTM.txt name. self.utm_zone
        # is None only when EVERY __convert_to_utm call failed, and the
        # resulting flight_log_UNKNOWN_UTM.txt used to be picked up by
        # find_flight_log, parsed as "no zone tag", and therefore treated
        # downstream as a LOCAL-frame (geocent / local:1) campaign - the
        # frame guard bypassed by its own naming convention
        # (audit 2026-08-07). A name outside the flight_log*_UTM.txt glob
        # cannot be mistaken for either frame.
        if self.utm_zone:
            flight_log_filename = os.path.join(
                image_folder, f"flight_log_{self.utm_zone}_UTM.txt")
        else:
            flight_log_filename = os.path.join(
                image_folder, "flight_log_UNRESOLVED.txt")
            self.logger.error(
                'No UTM zone could be resolved (no row carried usable '
                'lat/lon), so the output is named %s and is deliberately '
                'OUTSIDE the flight_log*_UTM.txt discovery glob - it must '
                'not be mistaken for a local-frame log.',
                os.path.basename(flight_log_filename))

        if os.path.exists(flight_log_filename):
            self.logger.warning(f"Flight log file already exists: {flight_log_filename}, overriding.")
            os.remove(flight_log_filename)

        accepted_images = [img for img in image_data if img.get("ACCEPTED", False)]
        decl_deg = self.params['magnetic_declination_deg'].get_value()

        # Uncertainty knobs (provenance + defaults: PRIOR_ACCURACY_DEFAULTS
        # at module scope). Operator-settable via --g_pos_accuracy /
        # --g_alt_accuracy / --g_orientation_accuracy since 2026-08-07;
        # before that they were literals here and in geoall.py.
        pos_x_acc = pos_y_acc = self._accuracy('geo_pos_accuracy_m', 'pos_xy')
        alt_acc = self._accuracy('geo_alt_accuracy_m', 'alt')
        yaw_acc = self._accuracy('geo_orientation_accuracy_deg', 'yaw')
        roll_acc = self._accuracy('geo_orientation_accuracy_deg', 'roll')
        self.stats['pos_accuracy_m'] = pos_x_acc
        self.stats['alt_accuracy_m'] = alt_acc
        self.stats['orientation_accuracy_deg'] = yaw_acc

        with open(flight_log_filename, "w") as f:
            f.write(
                "filename;X (East);Y (North);Alt;X Accuracy;Y Accuracy;Alt Accuracy;Yaw;Pitch;Roll;Yaw Accuracy;Pitch Accuracy;Roll Accuracy\n"
            )

            for image in accepted_images:
                heading_mag = image.get("HEADING_MAG")
                pitch_vehicle = image.get("PITCH_VEHICLE")
                roll_vehicle = image.get("ROLL_VEHICLE")

                camera_pitch_offset = self._get_camera_pitch_offset(image["FILENAME"])
                rc_yaw, rc_pitch, rc_roll = self._convert_to_rc_orientation(
                    heading_mag, pitch_vehicle, roll_vehicle, camera_pitch_offset, decl_deg
                )

                pitch_acc = self._get_camera_pitch_accuracy(image["FILENAME"])

                def fmt(val):
                    return f"{val:.6f}" if val is not None else ""

                line = ";".join([
                    image["FILENAME"],
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

        self.stats['written_to_flight_log'] = len(accepted_images)
        self.stats['rows_without_pitch_prior'] = sum(
            1 for img in accepted_images
            if img["FILENAME"] in self._no_mount_stems)
        print(f"Flight log: {flight_log_filename}")
        print(f"  Lines written: {self.stats['written_to_flight_log']}")
        if self.stats['rows_without_pitch_prior']:
            print(f"  Rows with NO pitch prior (unmeasured mount): "
                  f"{self.stats['rows_without_pitch_prior']}")

        return flight_log_filename

    def run(self):
        # Parameters are validated by the orchestrator before run()
        flight_log = self.params['geo_input_flight_log'].get_value()
        if 'geo_input_image_dir' in self.params:
            input_dir = self.params['geo_input_image_dir'].get_value()
        else:
            input_dir = os.path.join(self.params['output_dir'].get_value(), "raw_images")

        input_type = self.params['geo_input_type'].get_value()
        output_data = {}

        try:
            data_rows = self.__read_csv_data(flight_log)
            image_data = self.__read_image_filenames(input_dir, input_type)
            matches_made = self.__estimate_location(image_data, data_rows, input_type)
            output_path = self.__generate_flight_log(image_data, input_dir)

            output_data['Success'] = True
            output_data['CSV Rows'] = int(self.stats.get('csv_rows', 0))
            output_data['Files Listed'] = int(self.stats.get('files_listed', 0))
            output_data['Files Skipped By Extension'] = int(
                self.stats.get('files_skipped_by_extension', 0))
            output_data['Files Unreadable'] = int(self.stats.get('files_unreadable', 0))
            output_data['Timestamp Parse Failures'] = int(self.stats.get('timestamp_parse_failures', 0))
            output_data['Images With Valid Timestamps'] = int(self.stats.get('images_with_valid_ts', 0))
            output_data['Images Examined'] = int(self.stats.get('examined_images', 0))
            output_data['Matched <=2s'] = matches_made
            output_data['Rejected >2s'] = int(self.stats.get('rejected_time', 0))
            output_data['Rejected No CSV'] = int(self.stats.get('rejected_no_csv', 0))
            output_data['Written To Flight Log'] = int(self.stats.get('written_to_flight_log', 0))
            output_data['Acceptance Rate %'] = float(f"{self.stats.get('accept_rate_pct', 0.0):.2f}")
            output_data['Delta Buckets'] = {
                "Exact": int(self.stats.get('bucket_exact', 0)),
                "0-4s": int(self.stats.get('bucket_0_4', 0)),
                "4-15s": int(self.stats.get('bucket_4_15', 0)),
                ">15s": int(self.stats.get('bucket_gt15', 0))
            }
            output_data['Unknown Camera Images'] = int(self.stats.get('unknown_camera_images', 0))
            output_data['Accepted Field Gaps'] = {
                "Missing UTM": int(self.stats.get('accepted_missing_utm', 0)),
                "Missing Orientation": int(self.stats.get('accepted_missing_orientation', 0))
            }
            output_data['Output Flight Log'] = output_path
            output_data['Rows Without Pitch Prior'] = int(
                self.stats.get('rows_without_pitch_prior', 0))
            output_data['Prior Accuracies'] = {
                'Position m': self.stats.get('pos_accuracy_m'),
                'Altitude m': self.stats.get('alt_accuracy_m'),
                'Orientation deg': self.stats.get('orientation_accuracy_deg'),
            }

            # ---- acceptance gate ------------------------------------
            # Success used to be set unconditionally, so a dive whose
            # images matched the nav table 0% (wrong nav CSV, wrong
            # --g_type, clock offset) or 4% flowed downstream looking
            # complete: batching zoned the survivors, and align/merge/model
            # all "succeeded" on a fraction of the dive (audit 2026-08-07).
            floor_param = (self.params or {}).get('geo_min_accept_rate_pct')
            floor = 80.0 if floor_param is None else float(
                floor_param.get_value() or 0.0)
            rate = float(self.stats.get('accept_rate_pct', 0.0))
            gate_detail = (
                f"examined={output_data['Images Examined']} "
                f"accepted={matches_made} ({rate:.1f}%) "
                f"rejected_time={output_data['Rejected >2s']} "
                f"rejected_no_csv={output_data['Rejected No CSV']} "
                f"timestamp_parse_failures="
                f"{output_data['Timestamp Parse Failures']} "
                f"buckets={output_data['Delta Buckets']}")
            if matches_made == 0:
                self.logger.error(
                    'NO image matched the nav table within 2 s - there is no '
                    'flight log worth using. Check that the nav CSV covers '
                    'this dive, that --g_type matches the filename scheme, '
                    'and that the camera clock is not offset. %s', gate_detail)
                output_data['Success'] = False
                output_data['Failure'] = 'no images matched the nav table'
                return output_data
            if floor > 0 and rate < floor:
                self.logger.error(
                    'Acceptance rate %.1f%% is below the %.1f%% floor - only '
                    'part of this dive is georeferenced, and every later '
                    'stage would report success on that fraction. Lower '
                    '--g_min_accept_rate to accept it deliberately. %s',
                    rate, floor, gate_detail)
                output_data['Success'] = False
                output_data['Failure'] = (
                    f'acceptance rate {rate:.1f}% below the {floor:.1f}% floor')
                return output_data
            # Count IMAGES, not mount lookups. _unknown_camera_count is a
            # call counter: _mount_for is resolved three times per image
            # (lever arm, pitch offset, pitch accuracy), so measuring it
            # against files_listed made this fire at a THIRD unmeasured
            # cameras - measured: a 2-Cinema + 1-Starboard dive was refused
            # with "no image has a measured camera mount", which was false
            # (audit-verification 2026-08-07). rows_without_pitch_prior is
            # the per-image figure the same run already reports.
            no_mount_rows = int(self.stats.get('rows_without_pitch_prior', 0))
            written = int(self.stats.get('written_to_flight_log', 0))
            if no_mount_rows and no_mount_rows >= written > 0:
                self.logger.error(
                    'EVERY georeferenced image (%d of %d) belongs to a camera '
                    'family with no measured mount geometry (e.g. %s). Lever '
                    'arm and tilt would be invented for the whole dive - add '
                    'the family to modules/cameras.json and its mount to '
                    'georeference_images.MOUNTS before trusting this run.',
                    no_mount_rows, written, self._unknown_camera_example)
                output_data['Success'] = False
                output_data['Failure'] = 'no image has a measured camera mount'
                return output_data

        except Exception as e:
            self.logger.error(f"Error processing data: {e}")
            return {"Success": False}

        self.logger.info(f"CSV Rows: {output_data['CSV Rows']}")
        self.logger.info(f"Files Listed: {output_data['Files Listed']}")
        self.logger.info(f"Files Unreadable: {output_data['Files Unreadable']}")
        self.logger.info(f"Timestamp Parse Failures: {output_data['Timestamp Parse Failures']}")
        self.logger.info(f"Images With Valid Timestamps: {output_data['Images With Valid Timestamps']}")
        self.logger.info(f"Images Examined: {output_data['Images Examined']}")
        self.logger.info(f"Matched <=2s: {output_data['Matched <=2s']}")
        self.logger.info(f"Rejected >2s: {output_data['Rejected >2s']}")
        self.logger.info(f"Rejected No CSV: {output_data['Rejected No CSV']}")
        self.logger.info(f"Written To Flight Log: {output_data['Written To Flight Log']}")
        self.logger.info(f"Acceptance Rate %: {output_data['Acceptance Rate %']}")
        self.logger.info(f"Delta Buckets: {output_data['Delta Buckets']}")
        self.logger.info(f"Accepted Field Gaps: {output_data['Accepted Field Gaps']}")

        if self.utm_zone:
            self.logger.info(f"UTM Zone Detected: {self.utm_zone}")
        else:
            self.logger.warning("UTM Zone could not be determined (no valid GPS data found).")

        if self._utm_crossings:
            lat, lon, natural = self._utm_crossing_example
            self.logger.warning(
                '%d nav row(s) lie OUTSIDE UTM zone %s and were projected '
                'into it anyway (e.g. lat %.5f lon %.5f is naturally zone '
                '%d). One continuous frame is correct for the single CRS '
                'this log declares, but eastings there exceed the normal '
                'zone range - confirm the survey really spans a zone '
                'boundary.', self._utm_crossings, self.utm_zone,
                lat, lon, natural)
            output_data['Rows Outside Pinned UTM Zone'] = self._utm_crossings

        return output_data

    def validate_parameters(self) -> tuple[bool, str | None]:
        success, message = super().validate_parameters()
        if not success:
            return success, message

        if 'geo_input_image_dir' in self.params:
            input_dir = self.params['geo_input_image_dir'].get_value()
        else:
            input_dir = os.path.join(self.params['output_dir'].get_value(), "raw_images")

        if 'geo_input_flight_log' not in self.params:
            return False, 'Flight log parameter not found'

        flight_log = self.params['geo_input_flight_log'].get_value()

        if not os.path.isdir(input_dir):
            return False, 'Input directory does not exist'
        if not os.path.isfile(flight_log):
            return False, 'Flight log file does not exist'
        if os.path.splitext(flight_log)[1].lower() != '.csv':
            return False, 'Flight log is not a CSV file'

        if 'geo_input_type' not in self.params:
            return False, 'Data type parameter not found'

        dtype_value = self.params['geo_input_type'].get_value()
        if not dtype_value:
            return False, 'No data type specified (Zeuss, WCA, WCA2025, or All)'
        dtype = dtype_value.lower()
        if dtype not in ["zeuss", "wca", "wca2025", "all"]:
            return False, 'Invalid data type specified'

        if dtype == "wca":
            self.params['geo_input_type'].set_value("WCA")
        elif dtype == "zeuss":
            self.params['geo_input_type'].set_value("Zeuss")
        elif dtype == "wca2025":
            self.params['geo_input_type'].set_value("WCA2025")
        elif dtype == "all":
            self.params['geo_input_type'].set_value("All")

        return True, None