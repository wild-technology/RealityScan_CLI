from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import warnings
import csv
import math
from pathlib import Path
from dataclasses import asdict

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
from .. import image_exts


def validate_selection_manifest(manifest_path, input_dir, flight_log, *, cancelled=None):
    """Read-only low-level project gate. Approvals themselves belong to ReviewStore.

    Exact image/mask sets, bytes and selected navigation must agree BEFORE
    density/zoning or any batch write. Paths and record order are not identity.
    Returns a canonical content binding suitable for the batch fingerprint.
    """
    from ..source_inventory import file_hash
    from ..flight_logs import utm_zone_from_flight_log_name, epsg_for_utm_zone
    def checkpoint():
        if cancelled is not None and cancelled():
            raise InterruptedError('Selection manifest validation cancelled')
    checkpoint()
    path = Path(manifest_path).resolve()
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(manifest, dict) or manifest.get('schema') != 1:
        raise ValueError('Selection manifest schema must be 1')
    owner_root = next((p for p in path.parents if (p / '.rovscan-owner.json').is_file()), None)
    if owner_root is None or not path.is_relative_to(owner_root / 'proc'):
        raise ValueError('Selection manifest must be under its owned project proc tree')
    owner = json.loads((owner_root / '.rovscan-owner.json').read_text(encoding='utf-8'))
    if not manifest.get('project_id') or manifest['project_id'] != owner.get('project_id'):
        raise ValueError('Selection manifest project ownership mismatch')
    for key in ('selection_hash', 'quality_review_hash', 'spatial_review_hash', 'flight_log_sha256'):
        digest = manifest.get(key)
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('Selection manifest requires ' + key)
    selection_root = path.parent
    root = Path(input_dir).resolve()
    if root != Path(manifest['images_root']).resolve() or not root.is_relative_to(selection_root):
        raise ValueError('Actual batch input differs from approved selected tree')
    log = Path(flight_log).resolve()
    if log != Path(manifest['flight_log']).resolve() or not log.is_relative_to(selection_root):
        raise ValueError('Actual batch flight log differs from approved selection')
    if file_hash(log, cancelled=cancelled) != manifest['flight_log_sha256']:
        raise ValueError('Selected flight log content changed')
    zone = utm_zone_from_flight_log_name(str(log))
    if zone is None or epsg_for_utm_zone(*zone) != manifest.get('epsg'):
        raise ValueError('Selected flight log UTM frame differs from manifest')
    expected = {}
    names, associated, image_hashes = {}, set(), set()
    for kind in ('images', 'masks'):
        records = manifest.get(kind, [])
        if not isinstance(records, list) or (kind == 'images' and not records):
            raise ValueError('Selection manifest needs a nonempty image list and valid mask list')
        for item in records:
            checkpoint()
            original = Path(item['path'])
            file = original.resolve()
            if (not original.is_absolute() or not file.is_relative_to(root) or file in expected
                    or image_exts.is_geometry_image(file) != (kind == 'images')):
                raise ValueError('Selection contains duplicate, redirected or misclassified image/mask paths')
            if kind == 'images':
                if file.suffix.lower() not in BatchDirectory.ACCEPTED_EXTENSIONS:
                    raise ValueError('Selected image format is unsupported by batching: ' + str(file))
                name = file.name.casefold()
                if name in names:
                    raise ValueError('Selected images have ambiguous duplicate basenames')
                if item['sha256'] in image_hashes:
                    raise ValueError('Selected images contain duplicate content')
                image_hashes.add(item['sha256'])
                names[name] = file
                associated.update(p.resolve() for p in image_exts.associated_masks(file))
            if file_hash(file, cancelled=cancelled) != item['sha256']:
                raise ValueError('Selected image/mask content changed: ' + str(file))
            expected[file] = (kind, item['sha256'])
    masks = {p for p, (kind, _) in expected.items() if kind == 'masks'}
    if masks != associated:
        raise ValueError('Selected masks do not match exactly associated image layers')
    actual = set()
    for directory, _, files in os.walk(root):
        checkpoint()
        for name in files:
            checkpoint()
            file = Path(directory) / name
            if file.suffix.lower() in image_exts.ALL_IMAGE_EXTS:
                resolved = file.resolve()
                if not resolved.is_relative_to(root) or resolved in actual:
                    raise ValueError('Selected tree contains redirected or aliased image/mask files')
                actual.add(resolved)
    if actual != set(expected):
        raise ValueError('Actual image/mask set differs from selection manifest')
    # A selected tree alone is insufficient: excluded flight-log points would
    # still distort density and zone membership before copying ever starts.
    seen = set()
    with log.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.reader(stream, delimiter=';')
        header = next(reader, [])
        if len(header) != 14 or [v.strip().casefold() for v in header[:4]] != [
                'filename', 'x (east)', 'y (north)', 'alt']:
            raise ValueError('Selected flight log must have the 14-column camera schema')
        for row in reader:
            checkpoint()
            if not row:
                continue
            name = row[0].replace('\\', '/').rsplit('/', 1)[-1].casefold()
            if (name not in names or name in seen or len(row) != 14
                    or not all(math.isfinite(float(v)) for v in row[1:])):
                raise ValueError('Selected flight log has unknown, duplicate or incomplete camera rows')
            if ('/' in row[0] or '\\' in row[0]) and Path(row[0]).resolve() != names[name]:
                raise ValueError('Selected flight log points outside the selected image identity')
            seen.add(name)
    if seen != set(names):
        raise ValueError('Selected flight log does not cover exactly the selected images')
    checkpoint()
    canonical = dict(manifest, images=sorted(manifest['images'], key=lambda i: i['path']),
                     masks=sorted(manifest.get('masks', []), key=lambda i: i['path']))
    return {'project_id': manifest['project_id'], 'selection_hash': manifest['selection_hash'],
            'manifest_sha256': hashlib.sha256(json.dumps(canonical, sort_keys=True,
                separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()}


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
        # First flight-log filename that matched nothing on disk - named in
        # the copy-accounting error so the operator sees the actual string.
        self._missing_example: str | None = None

    def get_parameters(self) -> dict[str, Parameter]:
        additional_params = {}

        additional_params['batch_target_images_per_zone'] = Parameter(
            name='Target Images Per Zone',
            cli_short='b_t',
            cli_long='b_target_images',
            type=int,
            default_value=6500,  # 3000 -> 6500, owner directive 2026-09-06
            description='Target number of images per zone (zones will be split/merged to approach this)',
            prompt_user=True
        )

        additional_params['batch_min_zone_size'] = Parameter(
            name='Minimum Zone Size',
            cli_short='b_min',
            cli_long='b_min_zone',
            type=int,
            # 1000 -> 4000. The owner directive (2026-09-06) said 5000; it is
            # 4000 because of the DEAD BAND. __adaptive_zone_creation splits
            # only when zone_size > max_size and merges an undersized zone only
            # when combined_size <= max_size, so whenever 2*min > max a pair of
            # sub-minimum zones can NEITHER merge NOR split and stays below the
            # floor permanently. 2*4000 == 8000 == max_size is the boundary
            # that closes the band; 5000/8000 would have opened one 2000 wide,
            # and with initial_k = ceil(21023/6500) = 4 the base zones average
            # 5,256 - only 5% above a 5000 floor, so landing inside the band
            # was likely, not hypothetical. validate_parameters() now refuses
            # the inconsistent case instead of leaving it to the zone table.
            default_value=4000,
            description='Minimum images in a zone (smaller zones will be merged)',
            prompt_user=False
        )

        additional_params['batch_max_zone_size'] = Parameter(
            name='Maximum Zone Size',
            cli_short='b_max',
            cli_long='b_max_zone',
            type=int,
            # 4000 -> 8000, owner directive 2026-09-06. NOTE this caps the BASE
            # zone: overlap donation runs afterwards (__create_batch_folders)
            # and is never re-capped, so the DELIVERED zone reaches
            # max * (1 + overlap/100) - 9,600 at the 20% default. The delivered
            # sizes are now reported explicitly rather than left to be
            # discovered in the align logs (FINDINGS 2026-08: a 7,842-image
            # zone shipped against a 6,000 cap for exactly this reason).
            default_value=8000,
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

        additional_params['batch_use_z'] = Parameter(
            name='Cluster With Depth (Z)',
            cli_short='b_z',
            cli_long='b_use_z',
            type=bool,
            default_value=False,
            description=('Include altitude/depth in zone clustering and 3D '
                         'overlap donation. For sites with tall vertical '
                         'structure (shipwreck masts/hull): XY-only zones are '
                         'vertical columns mixing depth strata whose imagery '
                         'shares no visual field, fragmenting every zone into '
                         'per-stratum components (ON2026 diagnosis '
                         '2026-07-30: zone_2 = 7 components in disjoint Z '
                         'bands over one 6x4 m footprint).'),
            prompt_user=False
        )

        additional_params['batch_xmp_priors'] = Parameter(
            name='Write XMP Calibration Priors',
            cli_short='b_x',
            cli_long='b_xmp_priors',
            type=bool,
            # False -> True, owner directive 2026-09-06.
            #
            # WHAT IT ACTUALLY BUYS, stated plainly because the history here is
            # bad: on the DEFAULT identity path (RS_LEGACY_XMP_IDENTITY unset
            # or "1") realityscan_interface.ensure_calibration_sidecars()
            # already recreates a calibration sidecar for every known camera on
            # every exit path, so this flag does not decide WHETHER sidecars
            # exist - it decides whether they exist BEFORE the first align
            # instead of after it. The delta is the numeric content:
            # FocalLength35mm and DistortionModel.
            #
            # TWO STANDING CAVEATS, neither retracted:
            #  - NA167 zone_13 A/B measured this prior content REDUCING
            #    registration 96.3% -> 89.6%.
            #  - cameras.json gives zeuss/cinema/sony DistortionModel=brown3
            #    while Metadata/AlignmentParams.xml sets a GLOBAL
            #    sfmDistortionModel=Division. Which wins is UNMEASURED
            #    (docs/rs-reference/05). On a single-family dive the grouping
            #    half of the prior is a no-op, so the contradiction is the only
            #    thing the flag introduces.
            # Enabled because the owner asked for it; validate per-rig.
            default_value=True,
            description=('Write per-camera XMP calibration priors into the zones. '
                         'ON by default (owner directive 2026-09-06). Caveats: the '
                         'NA167 zone_13 A/B showed this prior content REDUCING '
                         'registration (96.3% -> 89.6%), and cameras.json '
                         'DistortionModel may contradict the global '
                         'sfmDistortionModel in AlignmentParams.xml. Copy layout '
                         'only - pool layout shares one canonical image tree, '
                         'which is read-only, so sidecars are skipped there.'),
            prompt_user=False
        )

        additional_params['batch_zone_layout'] = Parameter(
            name='Zone Layout',
            cli_short='b_zl',
            cli_long='b_zone_layout',
            type=str,
            default_value='copy',
            description=('copy (legacy): zones hold physical per-zone COPIES of '
                         'their images - overlap donation duplicates files, so '
                         'the same image is a DIFFERENT camera in each zone and '
                         'overlapping-zone components share nothing at merge '
                         'time (the known merge no-fuse defect). '
                         'pool: zones hold NO images - each zone gets an '
                         '.imagelist of COMPLETE canonical source paths plus a '
                         'zone flight log whose filename column carries those '
                         'same full paths, so every zone references the ONE '
                         'on-disk file and overlap images are genuinely shared '
                         'cameras (owner directive 2026-08-08, '
                         'docs/FLIGHTLOG_ARCHITECTURE.md). pool requires the '
                         'align stage to add images from the .imagelist.'),
            prompt_user=False
        )

        return {**super().get_parameters(), **additional_params}

    FINGERPRINT_NAME = 'batch_inputs.json'

    def _require_selection_manifest(self):
        """Opt-in for legacy callers; sticky once this instance is project-bound."""
        path = os.environ.get('RS_SELECTION_MANIFEST')
        prior = getattr(self, '_selection_binding', None)
        if path is None and prior is None:
            return None
        if not path:
            raise ValueError('Project batching requires RS_SELECTION_MANIFEST')
        binding = validate_selection_manifest(path, self.__get_input_dir(), self.__get_flight_log_path())
        if prior is not None and prior != binding:
            raise ValueError('Project selection changed during batching; start a fresh attempt')
        self._selection_binding = binding
        return binding

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
        # EVERY parameter that changes zone membership belongs here. The
        # overlap distance ceiling was added 2026-07-28 and initially left
        # out - which would have let a re-run with a new ceiling silently
        # reuse zones built without one, the exact fail-open the guard was
        # written to close (final review, must-fix #1).
        # batch_xmp_priors added 2026-09-06 when it became a default: it does
        # not change zone MEMBERSHIP, but it changes what is on disk inside the
        # zone tree, and __copy_files skips any destination that already exists
        # BY NAME. Without it here, flipping the flag reuses a tree built
        # without sidecars and writes none - the same fail-open shape as the
        # overlap ceiling below, and invisible in the logs.
        keys = ('batch_target_images_per_zone', 'batch_min_zone_size',
                'batch_max_zone_size', 'batch_initial_overlap_percent',
                'batch_density_weight', 'batch_kde_bandwidth',
                'batch_overlap_max_distance_m', 'batch_use_z',
                'batch_zone_layout', 'batch_xmp_priors')
        input_dir = self.__get_input_dir()
        fingerprint = {
            'flight_log': os.path.basename(flight_log_path or ''),
            'flight_log_sha256': digest,
            'input_dir': os.path.normcase(os.path.abspath(input_dir)) if input_dir else None,
            'input_signature': self._source_signature(input_dir),
            'params': {k: str(self.params[k].get_value())
                       for k in keys if k in self.params},
        }
        selection = self._require_selection_manifest()
        if selection is not None:
            fingerprint['selection'] = selection
        prior_param = (self.params or {}).get('batch_xmp_priors')
        if prior_param is not None and prior_param.get_value():
            # Serializer fixes and approved profile overrides must invalidate
            # a legacy batch even when filenames and all zoning knobs match.
            profile_bytes = json.dumps({k: asdict(v) for k, v in camera_registry.CAMERAS.items()},
                                       sort_keys=True, allow_nan=False).encode('utf-8')
            fingerprint['native_calibration'] = {
                'schema': 1,
                'serializer_sha256': hashlib.sha256(Path(camera_registry.__file__).read_bytes()).hexdigest(),
                'profiles_sha256': hashlib.sha256(profile_bytes).hexdigest(),
            }
        return fingerprint

    def _source_signature(self, input_dir: str | None) -> dict | None:
        """Cheap content signature of the image source: count, bytes, newest."""
        if not input_dir or not os.path.isdir(input_dir):
            return None
        count = 0
        total = 0
        newest = 0.0
        for root, _dirs, names in os.walk(input_dir):
            for n in names:
                if not image_exts.is_geometry_image(os.path.join(root, n), self.ACCEPTED_EXTENSIONS):
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

        comparable = {k: v for k, v in previous.items()
                      if k not in ('status', 'zone_flight_logs')}
        if comparable == current:
            if 'native_calibration' in current:
                try:
                    for zone in Path(output_dir).glob('zone_*'):
                        if zone.is_dir():
                            images = {p.resolve() for p in zone.rglob('*')
                                      if p.is_file() and image_exts.is_geometry_image(p)}
                            if images:
                                self.__assert_calibration_coverage(zone, images)
                except (OSError, ValueError) as exc:
                    return False, 'Existing batch calibration coverage is invalid: ' + str(exc)
            return True, None
        changed = [k for k in current if comparable.get(k) != current.get(k)]
        return False, (
            'Existing batched zones were built from DIFFERENT inputs '
            f'(changed: {", ".join(changed)}). Reusing them would mix two '
            'zonings, because copies are skipped but stale members are never '
            f'removed. {remedy}')

    def _zone_flight_log_shas(self, output_dir: str) -> dict:
        """sha256 of the flight log this run wrote into each zone folder.

        Provenance, not an input: modules.verify compares nav across the
        aligned zones, and every zone's log is a per-zone cut of ONE source
        log, so the per-zone shas differ by construction. This record lets
        the verifier tell "cut from the same source by the batcher" from
        "aligned with some other log" (NA173 F2 run, 2026-09-06). Excluded
        from the reuse comparison for the same reason status is.
        """
        out: dict = {}
        if not os.path.isdir(output_dir):
            return out
        for name in sorted(os.listdir(output_dir)):
            zone_dir = os.path.join(output_dir, name)
            if not (name.startswith('zone_') and os.path.isdir(zone_dir)):
                continue
            logs = sorted(f for f in os.listdir(zone_dir)
                          if f.startswith('flight_log')
                          and f.lower().endswith('.txt'))
            if not logs:
                continue
            h = hashlib.sha256()
            with open(os.path.join(zone_dir, logs[0]), 'rb') as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b''):
                    h.update(chunk)
            out[name] = {'file': logs[0], 'sha256': h.hexdigest()}
        return out

    def _zone_tree_has_images(self, output_dir: str) -> bool:
        """True when the batched tree already contains at least one image."""
        if not os.path.isdir(output_dir):
            return False
        for _root, _dirs, names in os.walk(output_dir):
            for n in names:
                if image_exts.is_geometry_image(os.path.join(_root, n), self.ACCEPTED_EXTENSIONS):
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
        if status == 'complete':
            data['zone_flight_logs'] = self._zone_flight_log_shas(output_dir)
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
        # find_flight_log REFUSES a directory whose logs disagree on UTM
        # zone (or mix tagged and untagged names). Surface that message
        # and return None so validate_parameters reports "a valid flight
        # log is required" instead of an argparse-era traceback escaping
        # to main.py (audit 2026-08-07).
        try:
            if 'geo_input_image_dir' in self.params:
                return find_flight_log(
                    self.params['geo_input_image_dir'].get_value())
            return find_flight_log(os.path.join(output_dir, "raw_images"),
                                   output_dir)
        except ValueError as exc:
            self.logger.error('%s', exc)
            return None

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

            # The X/Y columns were validated below but the NAME column
            # never was, so a log headed 'image;X (East);Y (North)' got
            # through here and blew up much later as a raw
            # `KeyError: 'filename'` inside __create_geographic_zones -
            # OUTSIDE run()'s try/except, i.e. an unhandled traceback out
            # of main.py (audit 2026-08-07).
            if 'filename' not in df.columns:
                self.logger.error(
                    "Flight log has no 'filename' (or 'Name') column - found "
                    "%s. RealityScan flight logs name the image in the first "
                    "column; rename it to 'Name' or 'filename'.",
                    list(df.columns))
                return None

            if 'X (East)' in df.columns and 'Y (North)' in df.columns:
                df = df.rename(columns={'X (East)': 'x', 'Y (North)': 'y'})
            elif 'x' not in df.columns or 'y' not in df.columns:
                self.logger.error("Flight log missing X (East) and Y (North) columns")
                return None

            df = df.dropna(subset=['x', 'y'])
            # Altitude column for Z-aware clustering (batch_use_z). Kept as a
            # plain 'z' column - geometry stays 2D so every existing plot and
            # geometry.x/y consumer is untouched. Missing/blank alt -> 0.
            alt_col = next((c for c in ('alt', 'Altitude', 'Alt')
                            if c in df.columns), None)
            df['z'] = (pd.to_numeric(df[alt_col], errors='coerce').fillna(0.0)
                       if alt_col else 0.0)
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
        """coords may be (n,2) XY or (n,3) XYZ (batch_use_z): every spatial
        column becomes a standardized feature; log-density is always the
        last feature and the only one down-weighted."""
        logd = np.log(density)
        features = np.column_stack([coords, logd])
        scaler = StandardScaler()
        X = scaler.fit_transform(features)
        X[:, -1] *= float(density_weight)
        km = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = km.fit_predict(X)
        return labels

    def _spatial_coords(self, gdf_like) -> np.ndarray:
        """(n,2) XY, or (n,3) XYZ when batch_use_z is on."""
        cols = [gdf_like.geometry.x.to_numpy(np.float64),
                gdf_like.geometry.y.to_numpy(np.float64)]
        use_z = (self.params or {}).get('batch_use_z')
        if use_z is not None and use_z.get_value():
            cols.append(gdf_like['z'].to_numpy(np.float64))
        return np.column_stack(cols)

    def __split_zone(self, zone_gdf, density_weight):
        """Split a zone into 2 sub-zones using density-aware k-means."""
        if len(zone_gdf) < 2:
            return [zone_gdf]

        coords = self._spatial_coords(zone_gdf)
        density = zone_gdf['density'].to_numpy()

        labels = self.__density_aware_kmeans(coords, density, 2, density_weight)

        return [zone_gdf[labels == 0].copy(), zone_gdf[labels == 1].copy()]

    def __find_nearest_zone(self, zone_gdf, other_zones):
        """Find the nearest zone based on centroid distance (3D when
        batch_use_z, so undersized strata merge with their own depth band
        rather than the column above/below them)."""
        zone_centroid = self._spatial_coords(zone_gdf).mean(axis=0)

        min_dist = float('inf')
        nearest_zone = None
        nearest_idx = None

        for idx, other_zone in enumerate(other_zones):
            if other_zone is zone_gdf:
                continue
            other_centroid = self._spatial_coords(other_zone).mean(axis=0)
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
        coords = self._spatial_coords(gdf)
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

        coords = self._spatial_coords(gdf)
        if coords.shape[1] == 3:
            self.logger.info("Z-aware batching: clustering and overlap "
                             "donation run in 3D (batch_use_z)")

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

                tree = cKDTree(self._spatial_coords(zone_i))
                other_xy = self._spatial_coords(other)
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
        previous per-file os.walk (O(images x tree size)).

        Keys are LOWERCASED: Windows filesystems are case-insensitive, so a
        log naming `C231C0001.JPG` against `C231C0001.jpg` on disk used to
        match nothing and produce zone folders holding zero images
        (audit 2026-08-07)."""
        by_name: dict[str, str] = {}
        by_stem: dict[str, str] = {}
        all_names: list[str] = []
        for root, _dirs, filenames in os.walk(input_dir):
            for fn in filenames:
                if not image_exts.is_geometry_image(os.path.join(root, fn)):
                    continue
                all_names.append(fn)
                by_name.setdefault(fn.lower(), os.path.join(root, fn))
                by_stem.setdefault(os.path.splitext(fn)[0].lower(), fn)
        return by_name, by_stem, all_names

    def __copy_files(self, input_dir, batch_folder_dir, files, file_index=None):
        """Copy files to camera-specific subfolders and generate XMP sidecars.

        Returns (copied, missing). Both used to be discarded: a missing
        file emitted one warning and `continue`d, and run() reported its
        image count from the flight-log rows assigned to zones, never from
        what actually landed on disk - so a whole-dive filename mismatch
        copied nothing and still returned Success with a plausible number
        (audit 2026-08-07).
        """
        if file_index is None:
            file_index = self.__index_files(input_dir)
        by_name, by_stem = file_index[0], file_index[1]
        copied = 0
        missing = 0
        prior_param = (self.params or {}).get('batch_xmp_priors')
        require_calibration = prior_param is not None and prior_param.get_value()

        # Flight-log rows may carry ABSOLUTE paths (export_rs_flightlog
        # --path-mode=absolute), while the on-disk index above is keyed by
        # bare lowercase basename - so resolution is by BASENAME. Two
        # different paths collapsing to one basename would then silently
        # copy the same indexed file under both rows' identities; refuse
        # loudly instead (colmap_studio FINDINGS C-20260827-06).
        claimed: dict[str, str] = {}
        expected_copies = set()
        requested_names = set()
        for file in files:
            raw = str(file)
            key = os.path.basename(raw).lower()
            prior = claimed.setdefault(key, raw)
            if prior.lower() != raw.lower():
                raise ValueError(
                    f"flight-log basename collision: '{prior}' and '{raw}' "
                    f"both map to '{key}' - basename lookup cannot tell "
                    "them apart (C-20260827-06)")

        for file in files:
            # Basename-normalized row name: the lookup key, the copied
            # file's name, and the sidecar stem (an absolute row must
            # never be os.path.join'd - it would swallow camera_dir).
            name = os.path.basename(str(file))
            if require_calibration and name.casefold() in requested_names:
                raise ValueError('Duplicate geometry image in batch request: ' + name)
            requested_names.add(name.casefold())
            file_path = by_name.get(name.lower())

            if file_path is None:
                missing += 1
                # Check if it's an extension mismatch
                base_name = os.path.splitext(name)[0]
                other_ext = by_stem.get(base_name.lower())
                if self._missing_example is None:
                    self._missing_example = file
                if other_ext:
                    self.logger.warning(f"File '{file}' not found, but found '{other_ext}' - flight log may have wrong extension")
                else:
                    self.logger.warning(f"File not found: {file} - flight log filename does not match any files in directory")
                continue
            copied += 1

            camera_subfolder = self.__determine_camera_subfolder(name, file_path)
            camera_dir = os.path.join(batch_folder_dir, camera_subfolder)
            os.makedirs(camera_dir, exist_ok=True)

            output_path = os.path.join(camera_dir, name)
            expected_copies.add(Path(output_path).resolve())
            if not os.path.exists(output_path):
                shutil.copy(file_path, output_path)
            image_exts.copy_associated_masks(file_path, output_path)

            # Optionally generate XMP sidecar with camera calibration priors
            # (self.params is None until the orchestrator injects it - treat
            # that the same as the parameter being absent/off)
            prior_param = (self.params or {}).get('batch_xmp_priors')
            if prior_param is not None and prior_param.get_value():
                self.__generate_xmp_sidecar(name, camera_dir, camera_subfolder)

        prior_param = (self.params or {}).get('batch_xmp_priors')
        if prior_param is not None and prior_param.get_value():
            if missing:
                raise ValueError('Calibration coverage incomplete: requested batch images are missing')
            self.__assert_calibration_coverage(batch_folder_dir, expected_copies)
        return copied, missing

    def __assert_calibration_coverage(self, directory, expected_images):
        """Fresh batch calibration is exact; exported component pose XMP is separate."""
        root = Path(directory).resolve()
        actual_images = {p.resolve() for p in root.rglob('*') if p.is_file() and image_exts.is_geometry_image(p)}
        if actual_images != expected_images:
            raise ValueError('Batch geometry image set differs from requested calibration coverage')
        expected_sidecars = {p.with_suffix('.xmp') for p in expected_images}
        if len(expected_sidecars) != len(expected_images):
            raise ValueError('Multiple geometry images collide on one calibration sidecar stem')
        actual_sidecars = {p.resolve() for p in root.rglob('*') if p.is_file() and p.suffix.casefold() == '.xmp'}
        if actual_sidecars != expected_sidecars:
            raise ValueError('Batch calibration sidecar set differs from geometry images')
        for path in expected_images:
            camera = camera_registry.identify(path.name)
            if camera is None:
                raise ValueError('Batch calibration sidecar is not current calibration-only registry output: ' + str(path))
            camera_registry.validate_calibration_xmp(path.with_suffix('.xmp').read_text(encoding='utf-8'), camera)

    def __generate_xmp_sidecar(self, image_filename: str, output_path: str, camera_type: str) -> None:
        """
        Generate XMP sidecar file for RealityScan camera calibration.

        Args:
            image_filename: Name of the image file
            output_path: Full path where the image is located
            camera_type: Camera type (zeuss, cammid, camupper, camlower, other)
        """
        if not image_exts.is_geometry_image(image_filename):
            return
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
            self._unknown_camera_count += 1
            if self._unknown_camera_example is None:
                self._unknown_camera_example = image_filename
            raise ValueError(f"Unknown camera type '{camera_type}' for required calibration: {image_filename}")

        # Fresh-input calibration only. Existing solved/exported pose XMP
        # belongs to the continuation lane and must not be overwritten.
        content = camera_registry.calibration_xmp(camera)
        camera_registry.validate_calibration_xmp(content, camera)
        path = Path(xmp_path)
        if path.exists():
            camera_registry.validate_calibration_xmp(path.read_text(encoding='utf-8'), camera)
            return
        with path.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(content)

    def __create_batch_folders(self, output_dir, zones, input_dir, flight_log_path=None):
        """
        Create per-zone folders and write zone-specific flight logs including all original columns.

        Returns (copied, missing) summed over every zone - what actually
        landed on disk, which is what run() reports and gates on.
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

        layout = 'copy'
        if 'batch_zone_layout' in (self.params or {}):
            layout = str(self.params['batch_zone_layout'].get_value()
                         or 'copy').strip().lower()
        if layout not in ('copy', 'pool'):
            raise ValueError(f"batch_zone_layout must be 'copy' or 'pool', "
                             f"got {layout!r}")
        if layout == 'pool':
            prior_param = (self.params or {}).get('batch_xmp_priors')
            if prior_param is not None and prior_param.get_value():
                # WARN AND SKIP, never raise. This used to be a ValueError,
                # which run() catches into {'Success': False} and main.py turns
                # into sys.exit(1) - so once batch_xmp_priors became a default
                # (True, owner directive 2026-09-06) that raise would have
                # killed EVERY pool run before a single zone was written, for a
                # default the operator never typed. The incompatibility is real
                # but it is a property of the layout, not an operator error:
                # pool zones hold no images, so the only place a sidecar could
                # go is beside the canonical source image, and that tree is
                # read-only (CLAUDE.md hard rule 0). Skipping is the correct
                # resolution; saying so loudly is the obligation.
                self.logger.warning(
                    'batch_xmp_priors is ON but zone layout is POOL - NO XMP '
                    'calibration sidecars will be written. Pool zones hold '
                    'only an .imagelist, and the canonical image tree is '
                    'read-only (hard rule 0), so there is nowhere to put them. '
                    'Calibration priors still reach the solve in-session via '
                    'prior_groups.py (-setPriorCalibrationGroup / '
                    '-setPriorLensGroup). Use copy layout if you specifically '
                    'need the per-image FocalLength/DistortionModel numerics.')
        elif flight_log_df is not None and any(
                os.path.isabs(str(n)) for n in flight_log_df.index[:50]):
            # A full-path master log zoned into COPY mode would write zone
            # logs whose rows name the POOL files while the scenes add the
            # zone COPIES - silently reintroducing the split-identity
            # defect pool mode exists to fix. Refuse loudly.
            raise ValueError("master flight log carries absolute image "
                             "paths - use batch_zone_layout='pool' "
                             "(copy mode would re-split image identity)")

        bar = self._initialize_loading_bar(len(zones), 'Creating Batch Folders')

        # Index the input tree once for all zones
        file_index = self.__index_files(input_dir)
        # A .tif/.heif dataset is recognised imagery elsewhere in the
        # pipeline (modules.image_exts.ALL_IMAGE_EXTS) but cannot be
        # batched here; say what is being left behind instead of filtering
        # it away in silence (audit 2026-08-07).
        skipped = image_exts.skipped_by_extension(
            file_index[2], self.ACCEPTED_EXTENSIONS)
        if skipped:
            self.logger.warning(
                '%d recognised image(s) under %s are NOT batched (%s): this '
                'stage copies only %s.', sum(skipped.values()), input_dir,
                ', '.join(f'{n} x {e}' for e, n in sorted(skipped.items())),
                ', '.join(sorted(self.ACCEPTED_EXTENSIONS)))
        total_copied = 0
        total_missing = 0

        for i, zone_files in enumerate(zones):
            batch_folder_name = f"zone_{i + 1}"
            batch_folder_dir = os.path.join(output_dir, batch_folder_name)
            os.makedirs(batch_folder_dir, exist_ok=True)

            unique_zone_files = list(dict.fromkeys(zone_files))
            if layout == 'pool':
                # No physical zone tree: resolve every zone member to its
                # ONE canonical on-disk file, write the .imagelist the
                # align stage adds from, and remember name->path for the
                # zone flight log below. Rows that resolve nowhere are
                # counted missing AND dropped from the log - a log row
                # naming an absent image fails the RS import (err:18002).
                by_name = file_index[0]
                path_of = {}
                zone_missing = 0
                for file in unique_zone_files:
                    if os.path.isabs(str(file)):
                        p = file if os.path.isfile(file) else None
                    else:
                        p = by_name.get(str(file).lower())
                    if p is None:
                        zone_missing += 1
                        if self._missing_example is None:
                            self._missing_example = file
                        self.logger.warning(
                            f'File not found for pool zone: {file}')
                        continue
                    path_of[file] = os.path.abspath(p)
                listfile = os.path.join(batch_folder_dir,
                                        f'{batch_folder_name}.imagelist')
                with open(listfile, 'w', encoding='utf-8', newline='') as fh:
                    fh.write('\r\n'.join(path_of.values()) + '\r\n')
                zone_copied = len(path_of)
            else:
                zone_copied, zone_missing = self.__copy_files(
                    input_dir, batch_folder_dir, unique_zone_files, file_index)
            total_copied += zone_copied
            total_missing += zone_missing

            # Create flight log per zone
            if flight_log_df is not None:
                # Maintain full column order
                members = (list(path_of) if layout == 'pool'
                           else unique_zone_files)
                zone_flight_log_df = flight_log_df.loc[
                    flight_log_df.index.isin(members)
                ].copy()

                # Keep original columns even if some missing
                missing = [col for col in flight_log_df.columns if col not in zone_flight_log_df.columns]
                for col in missing:
                    zone_flight_log_df[col] = ""

                if layout == 'pool':
                    # Rows carry the COMPLETE canonical path (owner
                    # directive 2026-08-08): every zone's rows name the
                    # same on-disk file, so overlap images are shared
                    # cameras and merges can fuse.
                    zone_flight_log_df.index = [
                        path_of[n] for n in zone_flight_log_df.index]

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

        return total_copied, total_missing

    def _explicit_param(self, name: str):
        """A parameter's value when it was EXPLICITLY supplied for this
        run, else None.

        The orchestrator sets every parameter from the command line, the
        'main' settings section, or the declared default - only the last
        of those is "unanswered", and only an unanswered parameter should
        defer to the 'batch' settings section.

        WHICH of the three it was is recorded on the Parameter itself
        (main.parse_arguments), never inferred from `value !=
        default_value`: a supplied value is allowed to EQUAL the declared
        default, and the inference then drops it silently. Measured on
        NA168 - --b_max_zone 4000 against the declared default of 4000
        read as absent, so the stored batch.max_zone_size=8000 won and a
        zone came out at 7,842 images against the 6,000 cap."""
        param = (self.params or {}).get(name)
        if param is None:
            return None
        value = param.get_value()
        return None if value is None or not param.is_explicit() \
            else value

    def _stored_default(self, key: str, fallback, cli_value=None):
        """Which value the prompt should offer as its default.

        An EXPLICIT caller value (a --b_min flag reaching the Parameter)
        must WIN over rs_settings.json; the stored value is only a
        convenience default for an unanswered prompt. Before this, the
        'batch' section beat the command line: with the repo's stored
        min_zone_size=300 (from NA173) and --b_min 2000, the batcher zoned
        at 300 - and because both keys feed _input_fingerprint, the wrong
        zoning was then recorded as legitimate provenance
        (audit 2026-08-07). Mirrors SettingsStore.ask's precedence, which
        already gets this right, and the reason the merge driver pins its
        options rather than inheriting them.
        """
        if cli_value is not None:
            return cli_value
        # The GATED lookup, never `get`: `get` bypasses
        # RS_NO_SETTINGS_INHERITANCE, so this helper used to inherit a
        # previous campaign's stored min/max even under refusal - the batcher
        # was the one module the strict agent lane could not actually make
        # strict (audit 2026-09-05; B8). Under refusal the fallback - the
        # Parameter's own value - stands.
        # Duck-typed: a SettingsStore-shaped test double only has to provide
        # `get` (the convention realityscan_env's docstring states), so fall
        # back to it rather than requiring the method.
        gated = (getattr(self.settings, 'default_for', None)
                 or getattr(self.settings, '_default_for', None))
        stored = (gated('batch', key, fallback) if callable(gated)
                  else self.settings.get('batch', key, fallback))
        # "Baked into code" only holds while nothing shadows the code default.
        # _prompt_int persists its resolved answer into section 'batch' on
        # EVERY run, including unattended EOF ones, so one run is enough to
        # freeze a value here forever after - and the operator is never told.
        # That is how stored min_zone_size=300 (from NA173) beat --b_min 2000,
        # and how batch.max_zone_size=8000 beat a 6,000 cap. It is not this
        # function's job to pick the winner (an operator's remembered answer is
        # a legitimate default), but it IS its job to say when the two differ.
        if stored != fallback:
            self.logger.warning(
                "rs_settings.json [batch] %s = %r is SHADOWING the code "
                "default %r for this run. The stored answer wins. Delete that "
                "key, or pass the flag explicitly, if you meant the code "
                "default to apply.", key, stored, fallback)
        return stored

    # Both prompts now DELEGATE to the shared typed lookup
    # (SettingsStore.ask_int / ask_float) rather than reimplementing the
    # precedence rule. They were byte-for-byte parallel implementations of
    # `ask` that had already drifted: they read the store ungated, so
    # RS_NO_SETTINGS_INHERITANCE did not reach the batcher. Keeping the
    # methods (rather than calling the store at every site) preserves the
    # 'batch' section name and the existing call signatures.

    def _prompt_typed(self, key, message, fallback, caster, type_name,
                      lo=None, hi=None, cli_value=None):
        """One implementation behind both numeric prompts.

        Delegates to SettingsStore.ask_int/ask_float when the store provides
        them (the real one does), so a production run uses the single shared
        lookup. Falls back to the local loop for SettingsStore-shaped test
        doubles, which by convention implement only ``get`` - both branches go
        through _stored_default, so the PRECEDENCE rule stays in one place
        either way.
        """
        shared = getattr(self.settings,
                         'ask_int' if caster is int else 'ask_float', None)
        if callable(shared):
            kwargs = {'message': message}
            if caster is float:
                kwargs.update(lo=lo, hi=hi)
            return shared('batch', key, cli_value, fallback, **kwargs)

        stored = self._stored_default(key, fallback, cli_value)
        while True:
            try:
                raw = input(f"{message} [{stored}]: ").strip()
            except EOFError:
                raw = ''
            try:
                value = caster(stored) if not raw else caster(raw)
            except (TypeError, ValueError):
                print(f"Please enter {type_name}.")
                continue
            if (lo is not None and value < lo) or (hi is not None and value > hi):
                print(f"Please enter a value between {lo} and {hi}.")
                continue
            break
        self.settings.set('batch', key, value)
        return value

    def _prompt_int(self, key: str, message: str, fallback: int,
                    cli_value=None) -> int:
        """Integer setting: CLI > stored 'batch' answer > code default."""
        return self._prompt_typed(key, message, fallback, int, 'an integer',
                                  cli_value=cli_value)

    def _prompt_float(self, key: str, message: str, fallback: float,
                      lo: float = None, hi: float = None,
                      cli_value=None) -> float:
        """Float setting: CLI > stored 'batch' answer > code default."""
        return self._prompt_typed(key, message, fallback, float, 'a number',
                                  lo=lo, hi=hi, cli_value=cli_value)

    # ------------------------------------------------------------------
    # THE zone-sizing lookup. Every consumer calls this one function.
    # ------------------------------------------------------------------
    def _resolve_zone_sizing(self, interactive_reprompt: bool = False):
        """(target, min, max, overlap) for this run, from ONE place.

        Owner directive 2026-09-06: sizing must resolve identically whether a
        run takes the code defaults or custom values. Before this there were
        three disagreeing sources:

        1. ``run()`` read ``self.params[...]`` directly after prompting min and
           max but NOT target - so target skipped the stored-answer layer that
           min/max went through;
        2. the interactive "(r)eject and set new params" branch OVERWROTE min
           and max with ``target*0.2`` and ``target*1.5``, discarding whatever
           the operator or the code default had said and silently inventing a
           new pair (at target 6500 that is min 1300 / max 9750 - nothing like
           the 4000/8000 policy);
        3. ``validate_parameters`` read the params a fourth time.

        All four now come through here, so a custom value and a default value
        travel the same road and the invariants are checked once.
        """
        target = self._prompt_int(
            'target_images', 'Target images per zone',
            self.params['batch_target_images_per_zone'].get_value(),
            cli_value=self._explicit_param('batch_target_images_per_zone')
            if not interactive_reprompt else None)
        min_size = self._prompt_int(
            'min_zone_size', 'Minimum zone size',
            self.params['batch_min_zone_size'].get_value(),
            cli_value=self._explicit_param('batch_min_zone_size')
            if not interactive_reprompt else None)
        max_size = self._prompt_int(
            'max_zone_size', 'Maximum zone size',
            self.params['batch_max_zone_size'].get_value(),
            cli_value=self._explicit_param('batch_max_zone_size')
            if not interactive_reprompt else None)
        overlap = self._prompt_float(
            'overlap_percent', 'Overlap percentage',
            self.params['batch_initial_overlap_percent'].get_value(),
            0.0, 100.0,
            cli_value=self._explicit_param('batch_initial_overlap_percent')
            if not interactive_reprompt else None)

        target, min_size, max_size = self._coerce_zone_sizing(
            int(target), int(min_size), int(max_size))

        # Write the resolved triple back onto the Parameters so that anything
        # still reading self.params (the fingerprint, the output dict) sees
        # exactly what the zoning used - the fingerprint recording a different
        # number from the run is how a wrong zoning became "legitimate
        # provenance" in the NA168 incident.
        self.params['batch_target_images_per_zone'].set_value(target)
        self.params['batch_min_zone_size'].set_value(min_size)
        self.params['batch_max_zone_size'].set_value(max_size)
        self.params['batch_initial_overlap_percent'].set_value(float(overlap))
        return target, min_size, max_size, float(overlap)

    def _coerce_zone_sizing(self, target: int, min_size: int, max_size: int):
        """Enforce min <= target <= max and close the dead band, loudly.

        validate_parameters REFUSES an inconsistent triple up front. This is
        the second line of defence for values that arrive later (an
        interactive re-prompt, a stored answer from another campaign), where
        refusing would throw away a completed clustering run. It repairs
        instead, and says exactly what it changed.
        """
        if min_size > max_size:
            self.logger.warning(
                'Zone sizing: min (%d) exceeded max (%d) - swapping them.',
                min_size, max_size)
            min_size, max_size = max_size, min_size
        if 2 * min_size > max_size:
            # See the batch_min_zone_size declaration: a pair of sub-minimum
            # zones can then neither merge nor split, permanently.
            repaired = max(1, max_size // 2)
            self.logger.warning(
                'Zone sizing: 2 * min (%d) exceeds max (%d), which creates a '
                'DEAD BAND where undersized zones can neither merge nor split. '
                'Lowering min to %d.', min_size, max_size, repaired)
            min_size = repaired
        if target < min_size:
            self.logger.warning('Zone sizing: target (%d) below min (%d) - '
                                'raising target to min.', target, min_size)
            target = min_size
        if target > max_size:
            self.logger.warning('Zone sizing: target (%d) above max (%d) - '
                                'lowering target to max.', target, max_size)
            target = max_size
        return target, min_size, max_size

    def run(self):
        try:
            self._require_selection_manifest()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.logger.error('Selection gate refused batching: %s', exc)
            return {'Success': False, 'Error': str(exc)}
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

        # ONE lookup for all four sizing knobs (see _resolve_zone_sizing).
        target_size, min_size, max_size, overlap_percent = \
            self._resolve_zone_sizing()
        self.logger.info(
            'Zone sizing in force: target %d, min %d, max %d, overlap %.1f%% '
            '(delivered zones may reach %d images).',
            target_size, min_size, max_size, overlap_percent,
            int(max_size * (1 + overlap_percent / 100.0)))

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

            # The zone plots are DIAGNOSTIC, and this call sits upstream of the
            # accept prompt and the file copy - so a rendering failure used to
            # throw away a completed clustering run and leave
            # batched_images_by_zone empty. Observed on NA165/H2060
            # (2026-08-31): 13 zones and 34,144 images computed, then
            # matplotlib 3.11.1 raised "'Path' object has no attribute
            # 'simplify_thresh'" out of savefig and the whole run died with
            # nothing written. Nothing downstream reads these PNGs, so a
            # failure here is logged and the batches still land on disk.
            try:
                self._require_selection_manifest()
                self.__plot_results(gdf_processed, final_zones, output_dir)
            except Exception as e:
                self.logger.warning(
                    f'Zone diagnostic plots failed ({type(e).__name__}: {e}). '
                    f'The batches themselves are unaffected and will still be '
                    f'written; only the PNGs are missing.')

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
                # Re-resolve through the SAME function the first pass used.
                # This branch used to prompt for target only and then DERIVE
                # min = target*0.2 and max = target*1.5, silently discarding
                # both the operator's values and the code defaults - at target
                # 6500 that produced min 1300 / max 9750 against a declared
                # 4000/8000 policy, and it bypassed every invariant check.
                # Now a rejected batch re-asks for all four knobs and the
                # result is coerced by the same rules as any other path.
                target_size, min_size, max_size, overlap_percent = \
                    self._resolve_zone_sizing(interactive_reprompt=True)
                self.logger.info(
                    'Re-zoning with target %d, min %d, max %d, overlap %.1f%%',
                    target_size, min_size, max_size, overlap_percent)

                self._require_selection_manifest()
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
            copied, missing = self.__create_batch_folders(
                output_dir, final_zones, input_dir, flight_log_path)

            # FAIL CLOSED on what actually landed on disk. The summary used
            # to be built from the ZONE LISTS ('Total Images in Batches'),
            # so a whole-dive filename mismatch - extension case, path-
            # qualified names in the log - copied nothing, reported
            # Success with a plausible number, wrote the 'complete'
            # fingerprint (which then blessed the empty tree for reuse) and
            # handed empty folders to alignment (audit 2026-08-07).
            if copied == 0:
                self.logger.error(
                    'ZERO images were copied into the zone folders: none of '
                    'the %d flight-log filename(s) matched a file under %s '
                    '(e.g. %r). The zoning is meaningless and the fingerprint '
                    'is deliberately left at "in_progress". Check that the '
                    'flight log belongs to this imagery.',
                    total_in_batches, input_dir, self._missing_example)
                return {'Success': False, 'Images Copied': 0,
                        'Images Missing': missing,
                        'Output Directory': output_dir}
            if missing:
                self.logger.error(
                    '%d of %d zone member(s) were NOT found under %s '
                    '(e.g. %r) - those images are absent from the zones and '
                    'from the alignment that follows.',
                    missing, total_in_batches, input_dir,
                    self._missing_example)
                if missing > total_in_batches // 2:
                    return {'Success': False, 'Images Copied': copied,
                            'Images Missing': missing,
                            'Output Directory': output_dir}

            self._write_fingerprint(output_dir, flight_log_path, status='complete')

            avg_zone_size = total_in_batches / len(final_zones) if final_zones else 0

            # DELIVERED sizes, per zone. max_zone_size caps the BASE zone;
            # overlap donation runs afterwards and is never re-capped, so the
            # count that actually reaches AlignZone.bat has never been reported
            # anywhere. FINDINGS 2026-08 records a 7,842-image zone (6,535 base
            # + 1,307 donated) shipping against a 6,000 cap precisely because
            # nothing printed this. Also surface any zone left under the floor
            # (the dead band is now refused in validate_parameters, but an
            # isolated cluster with no merge partner can still land low).
            delivered = sorted((len(z) for z in final_zones), reverse=True)
            self.logger.info(
                'DELIVERED zone sizes (base + donated overlap, the counts the '
                'aligner receives): %s', ', '.join(str(n) for n in delivered))
            if delivered and max_size and delivered[0] > max_size:
                self.logger.warning(
                    'Largest delivered zone is %d images against a max_zone of '
                    '%d - the excess is donated overlap, which is not capped. '
                    'Budget alignment memory against %d.',
                    delivered[0], max_size, delivered[0])
            undersized = [n for n in delivered if min_size and n < min_size]
            if undersized:
                self.logger.warning(
                    '%d zone(s) are BELOW the minimum of %d (%s) - they had no '
                    'merge partner within the max_zone budget. They will still '
                    'be aligned; small zones fragment more readily.',
                    len(undersized), min_size,
                    ', '.join(str(n) for n in undersized))

            output = {
                'Success': True,
                'Number of Zones': len(final_zones),
                'Target Zone Size': target_size,
                'Average Zone Size': int(avg_zone_size),
                'Delivered Zone Sizes': delivered,
                'Final Overlap': f"{overlap_percent}%",
                'Total Unique Images': len(gdf),
                'Total Images in Batches': total_in_batches,
                'Images Copied': copied,
                'Images Missing': missing,
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
        try:
            self._require_selection_manifest()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return False, 'Selection gate refused batching: ' + str(exc)
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

        # min <= target <= max, and the DEAD BAND. Nothing checked these before
        # (only `target < 100`), so an inconsistent triple was discoverable
        # only by reading the zone table afterwards - or not at all.
        #
        # The dead band: __adaptive_zone_creation splits a zone only when
        # zone_size > max_size, and merges an undersized zone only when
        # combined_size <= max_size. So when 2*min > max, a pair of
        # sub-minimum zones can NEITHER merge (their sum exceeds max) NOR
        # split (each is under max) - they stay below the floor for good, and
        # nothing reports it. Refused rather than warned: an operator who
        # types an inconsistent triple gets a silently degraded zoning that
        # costs GPU-hours to discover.
        min_size = None
        max_size = None
        if 'batch_min_zone_size' in self.params:
            min_size = self.params['batch_min_zone_size'].get_value()
        if 'batch_max_zone_size' in self.params:
            max_size = self.params['batch_max_zone_size'].get_value()
        if min_size is not None and max_size is not None:
            if min_size > max_size:
                return False, (f'Minimum zone size ({min_size}) exceeds maximum '
                               f'({max_size}).')
            if not (min_size <= target <= max_size):
                return False, (f'Target zone size ({target}) is outside '
                               f'[min {min_size}, max {max_size}].')
            if 2 * min_size > max_size:
                return False, (
                    f'DEAD BAND: 2 * min_zone ({min_size}) = {2 * min_size} '
                    f'exceeds max_zone ({max_size}). Two undersized zones '
                    f'could then neither merge (sum > max) nor split (each < '
                    f'max), so any zone landing under {min_size} would stay '
                    f'there permanently and silently. Raise --b_max_zone to at '
                    f'least {2 * min_size}, or lower --b_min_zone to at most '
                    f'{max_size // 2}.')
            # Overlap donation runs AFTER max_size is enforced and is never
            # re-capped, so state the number the aligner will actually see.
            delivered = int(max_size * (1 + (overlap or 0) / 100.0))
            self.logger.info(
                'Zone sizing: target %d, base range [%d, %d]. Overlap donation '
                'at %.1f%% is applied AFTER the max cap, so the DELIVERED zone '
                'may reach %d images - budget alignment against that number, '
                'not %d.', target, min_size, max_size, overlap or 0,
                delivered, max_size)

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
                try:
                    self._require_selection_manifest()
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    return False, 'Selection gate refused batching: ' + str(exc)
                shutil.rmtree(output_dir)

        if not os.path.isdir(output_dir):
            try:
                self._require_selection_manifest()
            except (OSError, ValueError, KeyError, TypeError) as exc:
                return False, 'Selection gate refused batching: ' + str(exc)
            os.makedirs(output_dir)

        return True, None
