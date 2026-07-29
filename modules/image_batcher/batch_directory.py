from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import warnings

import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib
import matplotlib.pyplot as plt
import seaborn as sns
from scipy.spatial import cKDTree, ConvexHull
from shapely.geometry import Point
from sklearn.cluster import KMeans
from sklearn.neighbors import KernelDensity
from sklearn.preprocessing import StandardScaler

from module_base.rs_module import RSModule
from module_base.parameter import Parameter
from module_base.settings_store import SettingsStore
from ..flight_logs import find_flight_log
from .. import camera_registry


class BatchDirectory(RSModule):
    ACCEPTED_EXTENSIONS = [".png", ".jpg", ".jpeg"]

    def __init__(self, logger):
        super().__init__("Batch Directory", logger)
        self.logger.info(f"Matplotlib {matplotlib.__version__}, Seaborn {sns.__version__}")
        self.utm_zone_suffix = None
        # Last-entered run-time answers (zone sizes etc.) persist as the
        # next run's defaults, like every other prompt in the pipeline
        self.settings = SettingsStore()
        self._unknown_camera_example: str | None = None
        self._unknown_camera_count = 0

    def get_parameters(self) -> dict[str, Parameter]:
        additional_params = {}

        additional_params['batch_target_images_per_zone'] = Parameter(
            name='Target Images Per Zone',
            cli_short='b_t',
            cli_long='b_target_images',
            type=int,
            default_value=3000,
            description='Target number of images per zone (zones will be split/merged to approach this)',
            prompt_user=True
        )

        additional_params['batch_min_zone_size'] = Parameter(
            name='Minimum Zone Size',
            cli_short='b_min',
            cli_long='b_min_zone',
            type=int,
            default_value=1000,  # <-- changed from 500 to 1000
            description='Minimum images in a zone (smaller zones will be merged)',
            prompt_user=False
        )

        additional_params['batch_max_zone_size'] = Parameter(
            name='Maximum Zone Size',
            cli_short='b_max',
            cli_long='b_max_zone',
            type=int,
            default_value=4000,
            description='Maximum images in a zone (larger zones will be split)',
            prompt_user=False
        )

        additional_params['batch_initial_overlap_percent'] = Parameter(
            name='Initial Overlap Percent',
            cli_short='b_p',
            cli_long='b_overlap_percent',
            type=float,
            default_value=20.0,
            description='The initial percent of overlap between batches.',
            prompt_user=True
        )

        additional_params['batch_overlap_max_distance_m'] = Parameter(
            name='Overlap Max Distance (meters, 0=uncapped)',
            cli_short='b_od',
            cli_long='b_overlap_max_distance',
            type=float,
            default_value=0.0,
            description='Donated overlap images further than this from the '
                        'receiving zone are dropped. 0 keeps the legacy '
                        'uncapped behaviour. The right band width is an OPEN '
                        'question (overlap probe, 2026-07-28) - what is not '
                        'open is that uncapped donation nullified H2023\'s '
                        'zoning entirely (zone_1 ended with 98.7%% of the '
                        'dive).',
            prompt_user=False
        )

        additional_params['batch_density_weight'] = Parameter(
            name='Density Weight (0..1)',
            cli_short='b_dw',
            cli_long='b_density_weight',
            type=float,
            default_value=0.3,
            description='Weight of density in clustering/overlap scoring (higher favors low-density boundaries).',
            prompt_user=False
        )

        additional_params['batch_kde_bandwidth'] = Parameter(
            name='KDE Bandwidth (meters, 0=auto)',
            cli_short='b_bw',
            cli_long='b_kde_bandwidth',
            type=float,
            default_value=0.0,
            description='Kernel density bandwidth. 0 uses Scotts rule.',
            prompt_user=False
        )

        additional_params['batch_input_image_dir'] = Parameter(
            name='Input Image Folder',
            cli_short='b_i',
            cli_long='b_input',
            type=str,
            default_value=None,
            description='Directory containing the images to batch',
            prompt_user=True,
            disable_when_module_active=['Extract Images', 'Preprocess Images']
        )

        additional_params['batch_flight_log_path'] = Parameter(
            name='Flight Log Path',
            cli_short='b_f',
            cli_long='b_flight_log_path',
            type=str,
            default_value=None,
            description='Path to the flight log file (required for geographic batching)',
            prompt_user=True,
            disable_when_module_active='Georeference Images'
        )

        additional_params['batch_xmp_priors'] = Parameter(
            name='Write XMP Calibration Priors',
            cli_short='b_x',
            cli_long='b_xmp_priors',
            type=bool,
            default_value=False,
            description=('Write per-camera XMP calibration priors into the zones. '
                         'Off by default: a naming bug meant historical runs never '
                         'actually loaded them, and the NA167 zone_13 A/B showed the '
                         'current prior content REDUCING registration (96.3% -> 89.6%). '
                         'Validate per-rig before enabling.'),
            prompt_user=False
        )

        return {**super().get_parameters(), **additional_params}

    FINGERPRINT_NAME = 'batch_inputs.json'

    def _input_fingerprint(self, flight_log_path: str) -> dict:
        """Identity of everything that determines what ends up in the zones.

        This covers the zoning inputs (flight log + parameters) AND THE IMAGE
        SOURCE. The source matters because `__get_input_dir` silently switches
        to <output>/preprocessed_images the moment that folder exists, and
        preprocess writes the SAME FILENAMES as the raw set - while
        `__copy_files` skips any destination that already exists BY NAME. So a
        fingerprint over the flight log alone is byte-identical between a raw
        run and a CLAHE run, the folder gets reused, every copy is skipped, and
        the zones still hold raw pixels that this project's own A/B says
        register at nearly zero. Nothing in the logs would distinguish it.
        The content signature is deliberately cheap - count, total bytes and
        newest mtime, no hashing - because it runs against tens of thousands of
        images and only has to detect "a different set of pixels".
        """
        digest = None
        if flight_log_path and os.path.isfile(flight_log_path):
            h = hashlib.sha256()
            with open(flight_log_path, 'rb') as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b''):
                    h.update(chunk)
            digest = h.hexdigest()
        keys = ('batch_target_images_per_zone', 'batch_min_zone_size',
                'batch_max_zone_size', 'batch_initial_overlap_percent',
                'batch_density_weight', 'batch_kde_bandwidth')
        input_dir = self.__get_input_dir()
        return {
            'flight_log': os.path.basename(flight_log_path or ''),
            'flight_log_sha256': digest,
            'input_dir': os.path.normcase(os.path.abspath(input_dir)) if input_dir else None,
            'input_signature': self._source_signature(input_dir),
            'params': {k: str(self.params[k].get_value())
                       for k in keys if k in self.params},
        }

    def _source_signature(self, input_dir: str | None) -> dict | None:
        """Cheap content signature of the image source: count, bytes, newest."""
        if not input_dir or not os.path.isdir(input_dir):
            return None
        count = 0
        total = 0
        newest = 0.0
        for root, _dirs, names in os.walk(input_dir):
            for n in names:
                if os.path.splitext(n)[1].lower() not in self.ACCEPTED_EXTENSIONS:
                    continue
                try:
                    st = os.stat(os.path.join(root, n))
                except OSError:
                    continue
                count += 1
                total += st.st_size
                newest = max(newest, st.st_mtime)
        return {'images': count, 'bytes': total, 'newest_mtime': round(newest, 0)}

    def _check_reuse_is_safe(self, output_dir: str, flight_log_path: str):
        """Refuse to reuse a zone folder built from DIFFERENT inputs.

        The unattended resume path reuses an existing batched folder, which is
        only sound while the flight log and batching parameters are unchanged -
        `__copy_files` skips files already present, so it cannot remove a zone
        member that the new zoning no longer wants. When the lever-arm fix
        changed every Port position, reuse left the previous zoning in place
        and the folders ended up holding 12,679 images against a reported
        9,834 (2026-07-26). Nothing detected it. Now the premise is checked.

        Returns (ok, message).
        """
        marker = os.path.join(output_dir, self.FINGERPRINT_NAME)
        current = self._input_fingerprint(flight_log_path)
        remedy = (f'Delete "{output_dir}" and re-run to rebuild cleanly.')

        # FAIL CLOSED on a missing or unreadable marker when zones already hold
        # images. The earlier version returned "safe" here, which is precisely
        # backwards: the marker used to be written only AFTER all copying, so
        # an interrupted copy - the exact case this guard exists for - left no
        # marker at all and sailed through. An empty tree is still fine to use.
        if self._zone_tree_has_images(output_dir):
            if not os.path.isfile(marker):
                return False, (
                    'Existing batched zones carry images but no '
                    f'{self.FINGERPRINT_NAME}, so what produced them is '
                    'unknown - most likely an interrupted copy. ' + remedy)
            try:
                with open(marker, encoding='utf-8') as fh:
                    previous = json.load(fh)
            except (OSError, ValueError) as exc:
                return False, (
                    f'{self.FINGERPRINT_NAME} is unreadable ({exc}), so reuse '
                    'cannot be justified. ' + remedy)
            if previous.get('status') != 'complete':
                return False, (
                    'Existing batched zones were left mid-build '
                    f'(status={previous.get("status")!r}), so the copy never '
                    'finished. ' + remedy)
        elif not os.path.isfile(marker):
            return True, None
        else:
            try:
                with open(marker, encoding='utf-8') as fh:
                    previous = json.load(fh)
            except (OSError, ValueError):
                return True, None

        comparable = {k: v for k, v in previous.items() if k != 'status'}
        if comparable == current:
            return True, None
        changed = [k for k in current if comparable.get(k) != current.get(k)]
        return False, (
            'Existing batched zones were built from DIFFERENT inputs '
            f'(changed: {", ".join(changed)}). Reusing them would mix two '
            'zonings, because copies are skipped but stale members are never '
            f'removed. {remedy}')

    def _zone_tree_has_images(self, output_dir: str) -> bool:
        """True when the batched tree already contains at least one image."""
        if not os.path.isdir(output_dir):
            return False
        for _root, _dirs, names in os.walk(output_dir):
            for n in names:
                if os.path.splitext(n)[1].lower() in self.ACCEPTED_EXTENSIONS:
                    return True
        return False

    def _write_fingerprint(self, output_dir: str, flight_log_path: str,
                           status: str = 'complete') -> None:
        """Record what these zones were built from.

        Written TWICE per run: 'in_progress' before any copying starts and
        'complete' after it finishes, so an interrupted copy leaves a marker
        that says so instead of leaving none at all.
        """
        data = self._input_fingerprint(flight_log_path)
        data['status'] = status
        try:
            with open(os.path.join(output_dir, self.FINGERPRINT_NAME), 'w',
                      encoding='utf-8') as fh:
                json.dump(data, fh, indent=2)
        except OSError as exc:
            self.logger.warning('Could not write batch fingerprint: %s', exc)

    @staticmethod
    def _show_if_interactive() -> None:
        """Show a figure only on EXPLICIT opt-in (RS_SHOW_PLOTS=1).

        plt.show() BLOCKS on an interactive backend until the window is
        dismissed, and the second plot cannot even appear until the first is
        closed (owner-observed). The previous guard inferred a human from
        sys.stdin.isatty() - but isatty() lies under hidden consoles (this
        repo's own Windows-traps list), and the batcher kept stalling for
        hours after the gate landed: 2 h 53 min between the two figure saves
        on a run with the gate 'active', against 1.35 s of actual zone
        computation (measured 2026-07-28). Presence of a human is not
        inferable here, so it must be declared. Both figures are always
        written as PNGs beside the zones; showing them is pure convenience.
        """
        if os.environ.get('RS_SHOW_PLOTS', '').strip() != '1':
            return
        try:
            plt.show()
        except Exception:
            pass

    def __get_input_dir(self):
        if 'batch_input_image_dir' in self.params:
            return self.params['batch_input_image_dir'].get_value()
        # Prefer the Preprocess Images output when that module ran (align on
        # processed copies, keep raw_images originals for texturing)
        preprocessed = os.path.join(self.params['output_dir'].get_value(), "preprocessed_images")
        if os.path.isdir(preprocessed):
            return preprocessed
        return os.path.join(self.params['output_dir'].get_value(), "raw_images")

    def __get_flight_log_path(self):
        if 'batch_flight_log_path' in self.params:
            return self.params['batch_flight_log_path'].get_value()
        # Georeference writes the flight log next to the images it
        # processed: its explicit input dir, or raw_images when it ran
        # after Extract Images (whose output the search must cover too).
        output_dir = self.params['output_dir'].get_value()
        if 'geo_input_image_dir' in self.params:
            return find_flight_log(self.params['geo_input_image_dir'].get_value())
        return find_flight_log(os.path.join(output_dir, "raw_images"), output_dir)

    def __read_flight_log_gdf(self, flight_log_path):
        if flight_log_path is None:
            return None

        filename = os.path.basename(flight_log_path)
        if "_UTM.txt" in filename:
            zone_part = filename.replace("flight_log_", "").replace("_UTM.txt", "")
            self.utm_zone_suffix = f"_{zone_part}"
        else:
            self.utm_zone_suffix = ""

        try:
            df = pd.read_csv(flight_log_path, delimiter=';')

            # Standardize to 'filename' column
            if 'Name' in df.columns:
                df = df.rename(columns={'Name': 'filename'})
            # If already 'filename', no change needed

            if 'X (East)' in df.columns and 'Y (North)' in df.columns:
                df = df.rename(columns={'X (East)': 'x', 'Y (North)': 'y'})
            elif 'x' not in df.columns or 'y' not in df.columns:
                self.logger.error("Flight log missing X (East) and Y (North) columns")
                return None

            df = df.dropna(subset=['x', 'y'])
            geometry = [Point(float(x), float(y)) for x, y in zip(df.x, df.y)]
            gdf = gpd.GeoDataFrame(df, geometry=geometry)

            return gdf
        except Exception as e:
            self.logger.error(f"Error reading or processing flight log: {e}")
            return None

    @staticmethod
    def __scott_bandwidth(xy: np.ndarray) -> float:
        n, d = xy.shape
        if n < 2:
            return 1.0
        std = np.std(xy, axis=0, ddof=1)
        s = float(np.mean(std))
        if s <= 0:
            s = 1.0
        factor = n ** (-1.0 / (d + 4.0))
        return max(s * factor, 1e-6)

    def __compute_density(self, coords: np.ndarray, bandwidth: float) -> np.ndarray:
        kde = KernelDensity(kernel='gaussian', bandwidth=bandwidth).fit(coords)
        log_d = kde.score_samples(coords)
        d = np.exp(log_d)
        d = np.maximum(d, np.finfo(np.float64).tiny)
        return d

    def __density_aware_kmeans(self, coords: np.ndarray, density: np.ndarray, k: int,
                               density_weight: float) -> np.ndarray:
        logd = np.log(density)
        features = np.column_stack([coords[:, 0], coords[:, 1], logd])
        scaler = StandardScaler()
        X = scaler.fit_transform(features)
        X[:, 2] *= float(density_weight)
        km = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = km.fit_predict(X)
        return labels

    def __split_zone(self, zone_gdf, density_weight):
        """Split a zone into 2 sub-zones using density-aware k-means."""
        if len(zone_gdf) < 2:
            return [zone_gdf]

        coords = np.column_stack([zone_gdf.geometry.x.to_numpy(np.float64),
                                  zone_gdf.geometry.y.to_numpy(np.float64)])
        density = zone_gdf['density'].to_numpy()

        labels = self.__density_aware_kmeans(coords, density, 2, density_weight)

        return [zone_gdf[labels == 0].copy(), zone_gdf[labels == 1].copy()]

    def __find_nearest_zone(self, zone_gdf, other_zones):
        """Find the nearest zone based on centroid distance."""
        zone_centroid = np.array([zone_gdf.geometry.x.mean(), zone_gdf.geometry.y.mean()])

        min_dist = float('inf')
        nearest_zone = None
        nearest_idx = None

        for idx, other_zone in enumerate(other_zones):
            if other_zone is zone_gdf:
                continue
            other_centroid = np.array([other_zone.geometry.x.mean(), other_zone.geometry.y.mean()])
            dist = np.linalg.norm(zone_centroid - other_centroid)

            if dist < min_dist:
                min_dist = dist
                nearest_zone = other_zone
                nearest_idx = idx

        return nearest_zone, nearest_idx

    def __adaptive_zone_creation(self, gdf, target_size, min_size, max_size, density_weight):
        """Create zones targeting specific image count with split/merge post-processing."""

        # Initial estimate of zones needed
        initial_k = max(2, int(np.ceil(len(gdf) / target_size)))
        self.logger.info(f"Starting with {initial_k} initial zones for {len(gdf)} images")

        # Initial clustering
        coords = np.column_stack([gdf.geometry.x.to_numpy(np.float64),
                                  gdf.geometry.y.to_numpy(np.float64)])
        density = gdf['density'].to_numpy()

        labels = self.__density_aware_kmeans(coords, density, initial_k, density_weight)
        gdf['cluster'] = labels

        zones = [gdf[gdf['cluster'] == i].copy() for i in range(initial_k)]

        # Iterative split/merge refinement
        max_iterations = 10
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            modified = False
            new_zones = []
            zones_to_merge = []

            for zone in zones:
                zone_size = len(zone)

                if zone_size > max_size:
                    # Split oversized zone
                    self.logger.info(f"Splitting zone with {zone_size} images")
                    split_zones = self.__split_zone(zone, density_weight)
                    new_zones.extend(split_zones)
                    modified = True

                elif zone_size < min_size:
                    # Mark for merging
                    zones_to_merge.append(zone)

                else:
                    # Zone is acceptable size
                    new_zones.append(zone)

            # Helper to remove a zone by identity
            def remove_zone_from_list(zone_list, target_zone):
                return [z for z in zone_list if z is not target_zone]

            # Process merges
            while zones_to_merge:
                small_zone = zones_to_merge.pop(0)

                # Find nearest zone from acceptable zones or other small zones
                search_zones = new_zones + zones_to_merge
                nearest_zone, nearest_idx = self.__find_nearest_zone(small_zone, search_zones)

                if nearest_zone is not None:
                    combined_size = len(small_zone) + len(nearest_zone)

                    if combined_size <= max_size:
                        # Merge zones
                        self.logger.info(f"Merging zones: {len(small_zone)} + {len(nearest_zone)} = {combined_size}")
                        merged = pd.concat([small_zone, nearest_zone])

                        # Remove nearest from its list
                        new_zones = remove_zone_from_list(new_zones, nearest_zone)
                        zones_to_merge = remove_zone_from_list(zones_to_merge, nearest_zone)

                        new_zones.append(merged)
                        modified = True
                    else:
                        # Can't merge, keep small zone
                        new_zones.append(small_zone)
                else:
                    # No zones to merge with, keep it
                    new_zones.append(small_zone)

            zones = new_zones

            if not modified:
                self.logger.info(f"Converged after {iteration} iterations")
                break

        # Renumber clusters
        for i, zone in enumerate(zones):
            zone['cluster'] = i

        # Combine back into single GeoDataFrame
        final_gdf = pd.concat(zones, ignore_index=True)

        return final_gdf, len(zones)

    def __create_geographic_zones(self, gdf, target_size, min_size, max_size,
                                  overlap_percent, density_weight, kde_bw,
                                  max_overlap_distance_m=0.0):
        if gdf is None or gdf.empty:
            return [], {}, None

        coords = np.column_stack([gdf.geometry.x.to_numpy(np.float64),
                                  gdf.geometry.y.to_numpy(np.float64)])

        bw = float(kde_bw)
        if bw <= 0.0:
            bw = self.__scott_bandwidth(coords)
        self.logger.info(f"KDE bandwidth used: {bw:.6g}")

        density = self.__compute_density(coords, bw)
        gdf['density'] = density

        # Adaptive zone creation
        gdf_processed, num_zones = self.__adaptive_zone_creation(
            gdf, target_size, min_size, max_size, density_weight
        )

        base_zones_gdf = [gdf_processed[gdf_processed['cluster'] == i] for i in range(num_zones)]
        base_zones_files = {i: zone['filename'].tolist() for i, zone in enumerate(base_zones_gdf)}

        final_zones = []
        if overlap_percent > 0:
            for i in range(num_zones):
                zone_i = base_zones_gdf[i]
                other = gdf_processed[gdf_processed['cluster'] != i]

                final_zone_files = list(base_zones_files[i])

                if other.empty or zone_i.empty:
                    final_zones.append(final_zone_files)
                    continue

                # The donor pool is the ENTIRE rest of the dive, so the slice
                # below must be capped against it: sized only by the RECEIVER,
                # a large zone swallows most of everything else. Measured on
                # H2023 (2026-07-28): zone_1's 20% overlap = 756 images = 93%
                # of the whole remainder, leaving it with 4,540 of 4,598
                # unique images (98.7% of the dive) spanning all three
                # co-visibility blocks - the zoning was nullified. The cap is
                # symmetric: at most overlap_percent of the receiver AND at
                # most overlap_percent of the donor pool.
                overlap_size = int(len(zone_i) * (overlap_percent / 100.0))
                donor_cap = int(len(other) * (overlap_percent / 100.0))
                if donor_cap < overlap_size:
                    self.logger.info(
                        'zone %d: overlap capped by donor pool (%d -> %d of '
                        '%d donors)', i, overlap_size, donor_cap, len(other))
                    overlap_size = donor_cap
                if overlap_size <= 0:
                    final_zones.append(final_zone_files)
                    continue

                tree = cKDTree(np.column_stack([zone_i.geometry.x.to_numpy(np.float64),
                                                zone_i.geometry.y.to_numpy(np.float64)]))
                other_xy = np.column_stack([other.geometry.x.to_numpy(np.float64),
                                            other.geometry.y.to_numpy(np.float64)])
                dists, _ = tree.query(other_xy, k=1)

                # Optional absolute ceiling: an overlap image the matcher can
                # never bridge to the zone is pure duplicate weight. The band
                # width itself is unsettled (overlap probe) - 0 disables.
                if max_overlap_distance_m > 0:
                    in_range = dists <= max_overlap_distance_m
                    if not in_range.all():
                        self.logger.info(
                            'zone %d: %d donor(s) beyond %.1f m dropped',
                            i, int((~in_range).sum()), max_overlap_distance_m)
                    other = other[in_range]
                    other_xy = other_xy[in_range]
                    dists = dists[in_range]
                    if other.empty:
                        final_zones.append(final_zone_files)
                        continue
                    overlap_size = min(overlap_size, len(other))

                other_density = other['density'].to_numpy()
                invdens = 1.0 / other_density

                d_ptp = np.ptp(dists)
                d_norm = (dists - dists.min()) / (d_ptp if d_ptp > 0 else 1.0)

                invdens_ptp = np.ptp(invdens)
                invdens_norm = (invdens - invdens.min()) / (invdens_ptp if invdens_ptp > 0 else 1.0)

                w_d = 0.7
                w_den = 0.3 if density_weight <= 0 else min(max(density_weight, 0.0), 1.0)
                score = w_d * d_norm + w_den * invdens_norm

                idx = np.argsort(score)[:overlap_size]
                files_to_add = other.iloc[idx]['filename'].tolist()

                final_zone_files.extend(files_to_add)
                final_zones.append(final_zone_files)
        else:
            final_zones = [files for _, files in base_zones_files.items()]

        return final_zones, base_zones_files, gdf_processed

    def __plot_results(self, gdf, zones, output_dir):
        os.makedirs(output_dir, exist_ok=True)

        x = gdf.geometry.x.to_numpy(dtype=np.float64, copy=False)
        y = gdf.geometry.y.to_numpy(dtype=np.float64, copy=False)

        fig1, ax1 = plt.subplots(figsize=(12, 10))
        try:
            sns.kdeplot(x=x, y=y, ax=ax1, cmap="viridis", fill=True, levels=25, bw_adjust=1.0, thresh=None)
            sc = ax1.scatter(x, y, c=gdf['density'].to_numpy(), cmap='viridis', s=10)
            cbar = fig1.colorbar(sc, ax=ax1)
            cbar.set_label('Density')
        except Exception as e:
            self.logger.warning(f"seaborn.kdeplot failed ({type(e).__name__}: {e}). Falling back to manual grid.")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=RuntimeWarning)
                nx = ny = 200
                xmin, xmax = float(np.nanmin(x)), float(np.nanmax(x))
                ymin, ymax = float(np.nanmin(y)), float(np.nanmax(y))
                if xmax == xmin:
                    xmax = xmin + 1.0
                if ymax == ymin:
                    ymax = ymin + 1.0
                xi = np.linspace(xmin, xmax, nx)
                yi = np.linspace(ymin, ymax, ny)
                Xi, Yi = np.meshgrid(xi, yi)
                H, _, _ = np.histogram2d(x, y, bins=[nx, ny], density=True)
                Z = H.T
                zmin, zmax = float(np.nanmin(Z)), float(np.nanmax(Z))
                if not np.isfinite(zmin) or not np.isfinite(zmax) or zmax == zmin:
                    zmin, zmax = 0.0, 1.0
                levels = np.linspace(zmin, zmax, 25)
                levels = np.unique(levels)
                if levels.size < 2:
                    levels = np.array([zmin, zmax], dtype=float)
                cf = ax1.contourf(Xi, Yi, Z, levels=levels, cmap="viridis", antialiased=True)
                cbar = fig1.colorbar(cf, ax=ax1)
                cbar.set_label('Density (proxy)')
                sc = ax1.scatter(x, y, c=gdf['density'].to_numpy(), cmap='viridis', s=10)

        ax1.set_title('Kernel Density Estimation of Image Locations')
        ax1.set_xlabel('X (Easting)')
        ax1.set_ylabel('Y (Northing)')
        kernel_plot_path = os.path.join(output_dir, 'kernel_density.png')
        fig1.savefig(kernel_plot_path, bbox_inches='tight')
        self._show_if_interactive()
        plt.close(fig1)
        self.logger.info(f"Kernel density plot saved to: {kernel_plot_path}")

        fig2, ax2 = plt.subplots(figsize=(12, 10))
        palette = sns.color_palette("husl", len(zones))
        ax2.scatter(x, y, color='gray', s=10, alpha=0.2, label='All Points')

        for i, zone_files in enumerate(zones):
            zone_gdf = gdf[gdf['filename'].isin(zone_files)]
            color = palette[i]
            zx = zone_gdf.geometry.x.to_numpy(dtype=np.float64, copy=False)
            zy = zone_gdf.geometry.y.to_numpy(dtype=np.float64, copy=False)
            ax2.scatter(zx, zy, color=color, label=f'Zone {i + 1}', s=25, alpha=0.8)

            if len(zone_gdf) >= 3:
                try:
                    points = np.column_stack([zx, zy])
                    hull = ConvexHull(points)
                    for simplex in hull.simplices:
                        ax2.plot(points[simplex, 0], points[simplex, 1], color=color, linewidth=2.0)
                except Exception as e:
                    self.logger.warning(f"Could not generate convex hull for Zone {i + 1}: {e}")

        ax2.set_title('Image Batches by Geographic Zone')
        ax2.set_xlabel('X (Easting)')
        ax2.set_ylabel('Y (Northing)')
        ax2.legend()
        zones_plot_path = os.path.join(output_dir, 'batch_zones.png')
        fig2.savefig(zones_plot_path, bbox_inches='tight')
        self._show_if_interactive()
        plt.close(fig2)
        self.logger.info(f"Batch zones plot saved to: {zones_plot_path}")

    def __determine_camera_subfolder(self, filename, source_path=None):
        """Camera subfolder from the filename via the shared camera
        registry (modules/camera_registry.py -- one entry per physical
        camera). When the filename carries no camera token, fall back to
        the source file's parent directory."""
        camera = camera_registry.identify(filename)
        if camera is not None:
            return camera.key

        if source_path:
            parent = os.path.basename(os.path.dirname(source_path))
            if parent:
                return parent.lower()
        return "other"

    @staticmethod
    def __index_files(input_dir):
        """One walk over the input tree: filename -> full path, and
        stem -> filename for extension-mismatch diagnostics. Replaces the
        previous per-file os.walk (O(images x tree size))."""
        by_name: dict[str, str] = {}
        by_stem: dict[str, str] = {}
        for root, _dirs, filenames in os.walk(input_dir):
            for fn in filenames:
                by_name.setdefault(fn, os.path.join(root, fn))
                by_stem.setdefault(os.path.splitext(fn)[0], fn)
        return by_name, by_stem

    def __copy_files(self, input_dir, batch_folder_dir, files, file_index=None):
        """Copy files to camera-specific subfolders and generate XMP sidecars."""
        if file_index is None:
            file_index = self.__index_files(input_dir)
        by_name, by_stem = file_index

        for file in files:
            file_path = by_name.get(file)

            if file_path is None:
                # Check if it's an extension mismatch
                base_name = os.path.splitext(file)[0]
                other_ext = by_stem.get(base_name)
                if other_ext:
                    self.logger.warning(f"File '{file}' not found, but found '{other_ext}' - flight log may have wrong extension")
                else:
                    self.logger.warning(f"File not found: {file} - flight log filename does not match any files in directory")
                continue

            camera_subfolder = self.__determine_camera_subfolder(file, file_path)
            camera_dir = os.path.join(batch_folder_dir, camera_subfolder)
            os.makedirs(camera_dir, exist_ok=True)

            output_path = os.path.join(camera_dir, file)
            if not os.path.exists(output_path):
                shutil.copy(file_path, output_path)

            # Optionally generate XMP sidecar with camera calibration priors
            # (self.params is None until the orchestrator injects it - treat
            # that the same as the parameter being absent/off)
            prior_param = (self.params or {}).get('batch_xmp_priors')
            if prior_param is not None and prior_param.get_value():
                self.__generate_xmp_sidecar(file, camera_dir, camera_subfolder)

    def __generate_xmp_sidecar(self, image_filename: str, output_path: str, camera_type: str) -> None:
        """
        Generate XMP sidecar file for RealityScan camera calibration.

        Args:
            image_filename: Name of the image file
            output_path: Full path where the image is located
            camera_type: Camera type (zeuss, cammid, camupper, camlower, other)
        """
        # RealityScan's sidecar convention is <stem>.xmp (image.jpg ->
        # image.xmp). The previous f"{image_filename}.xmp" produced
        # image.jpg.xmp, which RealityScan silently ignores - every
        # calibration prior written that way was never loaded.
        xmp_path = os.path.join(output_path, f"{os.path.splitext(image_filename)[0]}.xmp")

        # Camera-specific calibration values come from the shared registry
        # (one entry per PHYSICAL camera; groups separate the EXIF-identical
        # WCA units, focals/models are owner-confirmed 2026-07-23).
        camera = camera_registry.identify(image_filename)
        if camera is None:
            # Unknown camera type - no calibration priors to write. Warn
            # once; per-image warnings would flood the log on a dataset
            # with an unrecognized naming scheme.
            self._unknown_camera_count += 1
            if self._unknown_camera_example is None:
                self._unknown_camera_example = image_filename
                self.logger.warning(
                    f"Unknown camera type '{camera_type}' (e.g. {image_filename}) - "
                    "skipping XMP calibration sidecars for these images. "
                    "Further warnings suppressed; total reported in summary.")
            return

        # Write XMP file (content shared with the post-align sidecar
        # sanitizer via camera_registry.calibration_xmp)
        try:
            with open(xmp_path, 'w', encoding='utf-8') as f:
                f.write(camera_registry.calibration_xmp(camera))
        except Exception as e:
            self.logger.error(f"Failed to write XMP file {xmp_path}: {e}")

    def __create_batch_folders(self, output_dir, zones, input_dir, flight_log_path=None):
        """
        Create per-zone folders and write zone-specific flight logs including all original columns.
        """
        if not zones:
            raise ValueError('No geographic zones were created.')

        flight_log_df = None
        if flight_log_path and os.path.isfile(flight_log_path):
            # Read all columns exactly as they appear
            flight_log_df = pd.read_csv(flight_log_path, delimiter=';', dtype=str, keep_default_na=False)
            if 'Name' in flight_log_df.columns:
                flight_log_df = flight_log_df.rename(columns={'Name': 'filename'})
            flight_log_df.set_index('filename', inplace=True)

        bar = self._initialize_loading_bar(len(zones), 'Creating Batch Folders')

        # Index the input tree once for all zones
        file_index = self.__index_files(input_dir)

        for i, zone_files in enumerate(zones):
            batch_folder_name = f"zone_{i + 1}"
            batch_folder_dir = os.path.join(output_dir, batch_folder_name)
            os.makedirs(batch_folder_dir, exist_ok=True)

            unique_zone_files = list(dict.fromkeys(zone_files))
            self.__copy_files(input_dir, batch_folder_dir, unique_zone_files, file_index)

            # Create flight log per zone
            if flight_log_df is not None:
                # Maintain full column order
                zone_flight_log_df = flight_log_df.loc[
                    flight_log_df.index.isin(unique_zone_files)
                ].copy()

                # Keep original columns even if some missing
                missing = [col for col in flight_log_df.columns if col not in zone_flight_log_df.columns]
                for col in missing:
                    zone_flight_log_df[col] = ""

                # Write out zone-specific flight log
                batch_flight_log_name = f'flight_log{self.utm_zone_suffix}_UTM.txt'
                batch_flight_log_path = os.path.join(batch_folder_dir, batch_flight_log_name)

                zone_flight_log_df.to_csv(
                    batch_flight_log_path,
                    sep=';',
                    index=True,
                    index_label='filename',
                    columns=flight_log_df.columns  # preserve column order
                )

            self._update_loading_bar(bar, 1)


    def _prompt_int(self, key: str, message: str, fallback: int) -> int:
        """Integer prompt whose last-entered value persists as the next
        run's default (rs_settings.json, section "batch").

        EOF-safe: unattended runs (hidden consoles report isatty()=True
        with an EOF stdin) silently take the stored/fallback value - the
        same convention as merge_zones/grow_zone ask()."""
        stored = self.settings.get('batch', key, fallback)
        while True:
            try:
                raw = input(f"{message} [{stored}]: ").strip()
            except EOFError:
                raw = ''
            if not raw:
                value = int(stored)
                break
            try:
                value = int(raw)
                break
            except ValueError:
                print("Please enter an integer.")
        self.settings.set('batch', key, value)
        return value

    def _prompt_float(self, key: str, message: str, fallback: float,
                      lo: float = None, hi: float = None) -> float:
        stored = self.settings.get('batch', key, fallback)
        while True:
            try:
                raw = input(f"{message} [{stored}]: ").strip()
            except EOFError:
                raw = ''
            try:
                value = float(stored) if not raw else float(raw)
            except ValueError:
                print("Please enter a number.")
                continue
            if lo is not None and value < lo or hi is not None and value > hi:
                print(f"Please enter a value between {lo} and {hi}.")
                continue
            break
        self.settings.set('batch', key, value)
        return value

    def run(self):
        # Parameters are validated by the orchestrator before run()
        output_dir = os.path.join(self.params['output_dir'].get_value(), 'batched_images_by_zone')
        input_dir = self.__get_input_dir()
        flight_log_path = self.__get_flight_log_path()

        gdf = self.__read_flight_log_gdf(flight_log_path)
        if gdf is None or gdf.empty:
            self.logger.error("Could not process flight log for geographic batching.")
            return {'Success': False}

        self.logger.info(f"Total number of georeferenced points: {len(gdf)}")

        # Prompt for min/max zone size based on total image count; the
        # last-entered values are offered as defaults on the next run
        self.logger.info(f"Recommended min zone size: {max(100, len(gdf) // 10)}")
        self.logger.info(f"Recommended max zone size: {max(1000, len(gdf) // 2)}")

        self.params['batch_min_zone_size'].set_value(self._prompt_int(
            'min_zone_size', 'Minimum zone size',
            self.params['batch_min_zone_size'].get_value()))
        self.params['batch_max_zone_size'].set_value(self._prompt_int(
            'max_zone_size', 'Maximum zone size',
            self.params['batch_max_zone_size'].get_value()))

        target_size = int(self.params['batch_target_images_per_zone'].get_value())
        min_size = int(self.params['batch_min_zone_size'].get_value())
        max_size = int(self.params['batch_max_zone_size'].get_value())
        overlap_percent = float(self.params['batch_initial_overlap_percent'].get_value())
        density_weight = float(self.params['batch_density_weight'].get_value())
        kde_bw = float(self.params['batch_kde_bandwidth'].get_value())
        max_overlap_distance_m = float(
            self.params['batch_overlap_max_distance_m'].get_value()
            if 'batch_overlap_max_distance_m' in self.params else 0.0)

        self.logger.info(f"Target zone size: {target_size} images (min: {min_size}, max: {max_size})")
        if self.utm_zone_suffix:
            self.logger.info(f"UTM zone suffix detected: {self.utm_zone_suffix}")

        while True:
            final_zones, base_zones, gdf_processed = self.__create_geographic_zones(
                gdf, target_size, min_size, max_size, overlap_percent, density_weight, kde_bw,
                max_overlap_distance_m=max_overlap_distance_m
            )

            print("\n--- Batch Summary ---")
            print(f"Total unique images: {len(gdf)}")
            print(f"Number of zones created: {len(final_zones)}")
            print(f"Target: {target_size} images/zone (min: {min_size}, max: {max_size})")
            print("\nPer-zone breakdown:")

            total_in_batches = 0
            for i in range(len(final_zones)):
                final_files_in_zone = list(dict.fromkeys(final_zones[i]))
                total_count = len(final_files_in_zone)
                base_count = len(base_zones[i])
                overlap_count = total_count - base_count
                total_in_batches += total_count

                status = "OK"
                if total_count > max_size:
                    status = "OVERSIZED"
                elif total_count < min_size:
                    status = "UNDERSIZED"

                print(
                    f"  Zone {i + 1}: {total_count:4d} images ({base_count:4d} base + {overlap_count:3d} overlap) [{status}]")

            print(f"\nTotal images across all batches: {total_in_batches}")
            print(f"Average zone size: {total_in_batches / len(final_zones):.0f} images")
            print("---------------------\n")

            self.__plot_results(gdf_processed, final_zones, output_dir)

            # EOF-safe: an unattended run cannot answer - auto-accept the
            # computed batches (the summary above is in the log for review).
            try:
                user_input = input("Accept these batches? (a)ccept, (r)eject and set new params: ").strip().lower()
            except EOFError:
                self.logger.info("Non-interactive run: batches auto-accepted.")
                user_input = 'a'
            if user_input == 'a':
                self.logger.info("Batches accepted. Proceeding to copy files.")
                break
            elif user_input == 'r':
                while True:
                    new_target = self._prompt_int('target_images', 'New target images per zone', target_size)
                    if new_target >= 100:
                        target_size = new_target
                        break
                    print("Please enter a value >= 100.")

                overlap_percent = self._prompt_float(
                    'overlap_percent', 'New overlap percentage', overlap_percent, 0.0, 100.0)

                # Update min/max based on new target
                min_size = max(100, int(target_size * 0.2))
                max_size = int(target_size * 1.5)

                if os.path.isdir(output_dir):
                    shutil.rmtree(output_dir)
                os.makedirs(output_dir)
                continue
            else:
                print("Invalid input. Please enter 'a' or 'r'.")

        try:
            # in_progress FIRST: if the copy dies half way, the next run must
            # find a marker saying "unfinished", not an absent one.
            self._write_fingerprint(output_dir, flight_log_path, status='in_progress')
            self.__create_batch_folders(output_dir, final_zones, input_dir, flight_log_path)
            self._write_fingerprint(output_dir, flight_log_path, status='complete')

            avg_zone_size = total_in_batches / len(final_zones) if final_zones else 0

            output = {
                'Success': True,
                'Number of Zones': len(final_zones),
                'Target Zone Size': target_size,
                'Average Zone Size': int(avg_zone_size),
                'Final Overlap': f"{overlap_percent}%",
                'Total Unique Images': len(gdf),
                'Total Images in Batches': total_in_batches,
                'Output Directory': output_dir,
                'UTM Zone': self.utm_zone_suffix or 'N/A'
            }
            if self._unknown_camera_count:
                output['Images Without Calibration XMP'] = (
                    f"{self._unknown_camera_count} (e.g. {self._unknown_camera_example})")
            return output
        except ValueError as e:
            self.logger.error(e)
            return {'Success': False}

    def validate_parameters(self) -> tuple[bool, str | None]:
        success, message = super().validate_parameters()
        if not success:
            return success, message

        if 'batch_target_images_per_zone' not in self.params:
            return False, 'Target images per zone parameter not found'

        target = self.params['batch_target_images_per_zone'].get_value()
        if target < 100:
            return False, 'Target images per zone must be at least 100'

        if 'batch_initial_overlap_percent' not in self.params:
            return False, 'Initial overlap percent parameter not found'

        overlap = self.params['batch_initial_overlap_percent'].get_value()
        if not (0 <= overlap <= 100):
            return False, 'Overlap percent must be between 0 and 100'

        input_dir = self.__get_input_dir()
        if not os.path.isdir(input_dir):
            return False, 'Input directory does not exist'

        flight_log_path = self.__get_flight_log_path()
        if not flight_log_path or not os.path.isfile(flight_log_path):
            return False, 'A valid flight log is required for geographic batching.'

        # Note: Image counting and min/max prompting now happens in run() method
        # after loading flight log data, not during validation

        output_dir = os.path.join(self.params['output_dir'].get_value(), 'batched_images_by_zone')
        if os.path.isdir(output_dir) and os.listdir(output_dir):
            self.logger.warning('Batched images folder already exists and may contain old plots. Overwrite? (y/n)')
            try:
                overwrite = input()
            except EOFError:
                # Unattended run: REUSE the existing folder without deleting
                # anything - zone recomputation is deterministic for the
                # same log+parameters and __copy_files skips files already
                # present, so this is the resume path, not data loss.
                # (Interactive 'y' still wipes for a truly clean rebuild.)
                # Reuse is ONLY sound while the inputs are unchanged; that
                # premise is now verified rather than asserted.
                safe, why = self._check_reuse_is_safe(output_dir, flight_log_path)
                if not safe:
                    return False, why
                self.logger.info('Non-interactive: reusing existing batched '
                                 'folder (copies are skipped if present).')
                overwrite = None
            if overwrite is not None:
                if overwrite.strip().lower() != 'y':
                    return False, 'Batched images folder not created'
                shutil.rmtree(output_dir)

        if not os.path.isdir(output_dir):
            os.makedirs(output_dir)

        return True, None