from __future__ import annotations

import os
import shutil

from module_base.rs_module import RSModule
from module_base.parameter import Parameter
from .. import camera_registry
from .. import component_manifest
from ..flight_logs import (ensure_frame_match, find_flight_log,
                           utm_zone_from_flight_log_name,
                           write_flight_log_params)
from .realityscan_cli import RealityScanCLI, METADATA_DIR, set_project_save_env

# Component/scene files as exported by RealityScan (legacy RealityCapture
# extensions still accepted so older outputs keep working).
COMPONENT_EXTENSIONS = ('.rsalign', '.rcalign')
SCENE_EXTENSIONS = ('.rsproj', '.rcproj')


class RealityScanAlignment(RSModule):
    def __init__(self, logger):
        super().__init__("RealityScan Alignment", logger)
        self.cli = RealityScanCLI(logger)

    def get_parameters(self) -> dict[str, Parameter]:
        additional_params = {}

        additional_params['rs_input_image_dir'] = Parameter(
            name='Input Image Folder',
            cli_short='r_i',
            cli_long='r_input',
            type=str,
            default_value=None,
            description='Directory containing the images to align (or folder of batched images)',
            prompt_user=True,
            disable_when_module_active='Batch Directory'
        )

        additional_params['rs_project_label'] = Parameter(
            name='Project Label',
            cli_short='r_p',
            cli_long='r_project_label',
            type=str,
            default_value='',
            description='expedition_dive label for the RC_projects daily save schema (e.g. NA156_H2023); empty disables daily saves',
            prompt_user=True
        )

        additional_params['rs_display_output'] = Parameter(
            name='Display Output',
            cli_short='r_d',
            cli_long='r_display_output',
            type=bool,
            default_value=False,
            description='Whether to display the RealityScan output',
            prompt_user=True
        )

        additional_params['rs_flight_log_path'] = Parameter(
            name='Flight Log Path',
            cli_short='r_f',
            cli_long='r_flight_log',
            type=str,
            default_value=None,
            description='Path to the flight log file',
            prompt_user=True,
            disable_when_module_active=['Batch Directory', 'Georeference Images']
        )

        additional_params['rs_model_generate'] = Parameter(
            name='Generate Model',
            cli_short='r_m',
            cli_long='r_model_generate',
            type=bool,
            default_value=True,
            description='Whether to automatically generate the model',
            prompt_user=True
        )

        additional_params['rs_model_cull_poly'] = Parameter(
            name='Model Polygon Culling',
            cli_short='r_c',
            cli_long='r_model_cull_poly',
            type=bool,
            default_value=True,
            description='Whether to automatically cull large and floating polygons on the generated model',
            prompt_user=True
        )

        additional_params['rs_model_texture'] = Parameter(
            name='Model Texturing',
            cli_short='r_t',
            cli_long='r_model_texture',
            type=bool,
            default_value=True,
            description='Whether to automatically texture the generated model',
            prompt_user=True
        )

        additional_params['rs_model_simplify'] = Parameter(
            name='Model Simplification',
            cli_short='r_s',
            cli_long='r_model_simplify',
            type=bool,
            default_value=True,
            description='Whether to automatically simplify the generated model',
            prompt_user=True
        )

        return {**super().get_parameters(), **additional_params}

    def __check_and_create_folder(self, path):
        """
        Checks if a folder exists, if not, creates it.
        """
        if not os.path.isdir(path):
            os.makedirs(path)
            self.logger.info(f"Created folder: {path}")

    def __get_flight_log_path(self, batch_path=None):
        """
        Returns the path to the flight log file (or None when none exists).

        All on-disk discovery goes through flight_logs.find_flight_log so
        the georeference module's flight_log_<zone>_UTM.txt naming and the
        per-zone copies from Batch Directory are both found.
        """

        # batched images: each zone folder carries its own flight log copy
        if batch_path is not None:
            return find_flight_log(batch_path)

        # if the flight log path is specified, use that
        if 'rs_flight_log_path' in self.params:
            return self.params['rs_flight_log_path'].get_value()

        # The georeference module writes its flight log next to the images
        # it processed: its explicit input dir, or raw_images when chained
        # after Extract Images.
        if 'geo_input_image_dir' in self.params:
            return find_flight_log(self.params['geo_input_image_dir'].get_value())
        output_dir = self.params['output_dir'].get_value()
        return find_flight_log(os.path.join(output_dir, "raw_images"), output_dir)

    def __align_zone(self, input_folder, output_folder, scene_name,
                     flight_log_path, flight_log_params_path,
                     display_output=False, min_component_size=50):
        """Align one zone as one scene via AlignZone.bat and export ALL its
        components (>= min_component_size cameras) plus a registration
        census. No model generation here: models are built once, on the
        merged component (GenerateModel.bat).

        All RealityScan execution goes through RealityScanCLI, which handles
        instance locking, progress monitoring, error detection, and verified
        instance shutdown (see realityscan_cli.py).
        """

        if not input_folder:
            raise ValueError("Input folder is not specified")

        if not os.path.isdir(input_folder):
            raise ValueError(f"Input folder {input_folder} is not a directory")

        # A re-run must start from a clean zone folder: stale exports would
        # be indistinguishable from this run's (exportLatestComponents
        # reuses names like "Component 0.rsalign") and would poison the
        # files_before/after diff below.
        if os.path.isdir(output_folder) and os.listdir(output_folder):
            self.logger.warning('Clearing previous exports in %s', output_folder)
            shutil.rmtree(output_folder)
        self.__check_and_create_folder(output_folder)

        if flight_log_path is None or not os.path.isfile(flight_log_path):
            # Never fail the run, but never be silent about it either:
            # aligning without a trajectory is a materially different run.
            self.logger.warning(
                'No flight log found for %s (looked for: %s) - aligning WITHOUT '
                'georeferencing priors', input_folder, flight_log_path or 'none')
            flight_log_path = ""

        if flight_log_params_path is None or not os.path.isfile(flight_log_params_path) or flight_log_path == "":
            flight_log_params_path = ""

        log_dir = os.path.join(os.path.dirname(os.path.dirname(output_folder)), "logs")

        # The params XML declares the trajectory's coordinate system. The
        # template's zone belongs to whatever cruise last edited it, so
        # regenerate it from the zone tag in the flight log's own filename
        # (flight_log_53N_UTM.txt -> EPSG:32653) whenever possible.
        if flight_log_path and flight_log_params_path:
            # Frame guard first - never import silently in the wrong frame
            # (2026-08-07 incident: the shared template carried ON2026's
            # local frame and poisoned a UTM 57L import; 3/32 registered,
            # exit code 0). Raises ValueError when the filename's implied
            # frame contradicts the template's declared frame; the write
            # below re-checks the same invariant as defense in depth.
            ensure_frame_match(flight_log_path, flight_log_params_path)
            zone_band = utm_zone_from_flight_log_name(flight_log_path)
            if zone_band is not None:
                zone, band = zone_band
                generated = os.path.join(log_dir, f'FlightLogParams_{zone}{band}.xml')
                flight_log_params_path = write_flight_log_params(
                    flight_log_params_path, generated, zone, band, frame='utm')
                self.logger.info(f'Flight log CRS: UTM zone {zone}{band} '
                                 f'(params: {generated})')
            else:
                self.logger.warning(
                    f'Flight log "{os.path.basename(flight_log_path)}" carries no '
                    'UTM zone tag - LOCAL-frame campaign; using the params '
                    'template as-is (frame checked: it does not declare UTM). '
                    'Verify this cruise really uses local:1 priors!')

        files_before = set(os.listdir(output_folder))

        result = self.cli.run_batch_script(
            'AlignZone.bat',
            [input_folder, output_folder, flight_log_path, flight_log_params_path,
             scene_name, str(min_component_size)],
            log_dir, display_output)

        # Sidecar hygiene even on failure: the in-session identity loop
        # normally harvests every pose sidecar into identity_c<K> folders,
        # but a partial run may leave pose sidecars beside the images,
        # which would poison the next attempt as auto-imported priors
        # (B7). The registration census now comes from the manifests
        # (harvested sidecars), not from this sweep.
        leftover, restored, removed = camera_registry.sanitize_and_census(input_folder)
        if leftover:
            self.logger.warning(
                '%d pose sidecars were left beside the images (partial '
                'identity harvest?) - restored/removed for hygiene',
                leftover)

        if not result.success:
            self.logger.error(f"RealityScan workflow failed for {input_folder}: "
                              f"{result.errors or f'exit code {result.return_code}'} (log: {result.log_path})")
            return {'Success': False, 'Component Count': 0,
                    'Registered Cameras': 0}, {'Success': False}

        component_files = [f for f in os.listdir(output_folder)
                           if f not in files_before and f.endswith(COMPONENT_EXTENSIONS)]

        # Verify the saved scene exists and is non-empty instead of
        # trusting the workflow's exit status alone.
        scene_path = os.path.join(output_folder, f"{scene_name}.rsproj")
        scene_success = os.path.isfile(scene_path) and os.path.getsize(scene_path) > 0
        if not scene_success:
            self.logger.error(f'Project file "{scene_path}" was not created')

        if not component_files:
            self.logger.error(
                'No components of >= %d cameras were exported for %s',
                min_component_size, input_folder)
            return {'Success': False, 'Component Count': 0,
                    'Registered Cameras': 0}, {'Success': scene_success}

        # Per-component identity: manifests built from the identity_c<K>
        # harvest folders written by AlignZone.bat's in-session loop (the
        # only place stem-named sidecars exist - FINDINGS 2026-07-23).
        # The registration census = sum of manifest camera counts. A
        # manifest failure does not fail the zone: alignment succeeded and
        # manifests are bookkeeping, but errors are logged loudly because
        # the merge stage depends on them.
        manifest_paths = []
        if scene_success:
            manifest_paths = self.capture_component_identities(
                input_folder, output_folder, scene_name, flight_log_path)
        # The identity harvest MOVES pose sidecars out of the image tree and
        # never re-exports the last-peeled component's, leaving those images
        # with no calibration prior at all. Left unrepaired, a later re-align
        # of this folder silently runs with a partially ungrouped camera set
        # (measured: 796 of 4,540 zone_1 images, FINDINGS 2026-07-25).
        camera_registry.ensure_calibration_sidecars(input_folder)

        registered = 0
        for mp in manifest_paths:
            try:
                registered += component_manifest.load_manifest(mp).get('camera_count', 0)
            except Exception as exc:
                self.logger.warning('Could not read manifest %s: %s', mp, exc)

        self.logger.info(
            'Zone %s: %d component(s) exported, %d cameras registered '
            '(census from %d manifest(s))',
            scene_name, len(component_files), registered, len(manifest_paths))

        component_data = {
            'Success': True,
            'Component Count': len(component_files),
            'Component Files': [os.path.join(output_folder, f) for f in component_files],
            'Registered Cameras': registered,
            'Manifests': manifest_paths,
        }
        scene_data = {'Success': scene_success, 'Scene Path': scene_path}
        return component_data, scene_data

    # Bounded per-component identity loop: zones fragment into 2-5
    # components; 20 is a generous ceiling against a pathological scene.
    MAX_IDENTITY_COMPONENTS = 20

    def capture_component_identities(self, input_folder, output_folder,
                                     scene_name, flight_log_path):
        """Build manifests from the identity_r<K> harvest folders written
        by AlignZone.bat's in-session identity loop.

        Public because drivers that invoke AlignZone.bat directly (the
        testing/ PD cells) must reuse THIS implementation - a component
        without a manifest is refused by the feature-aware merge.

        Naming rule (FINDINGS 2026-07-23, four consistent datapoints):
        -exportXMP writes STEM-named sidecars, while
        -exportXMPForSelectedComponent is always ORDINAL - so
        per-component membership comes from SUCCESSIVE DIFFERENCE: lap K
        harvests the stems of ALL components still in the scene
        (identity_r<K>), then the maximal component <scene>_c<K> is
        exported and deleted. members(c<K>) = stems(r<K>) - stems(r<K+1>).
        The harvest also displaced the calibration sidecars beside the
        images (pose exports overwrite <stem>.xmp and the harvest MOVES
        them), so calibration-only sidecars are regenerated here for
        every member (B7 hygiene is automatic).
        """
        # stem -> (image basename, full path), one walk of the zone tree
        stem_to_image = {}
        for root, _dirs, files in os.walk(input_folder):
            for f in files:
                if f.lower().endswith(('.jpg', '.jpeg', '.png', '.heif')):
                    stem_to_image.setdefault(
                        os.path.splitext(f)[0].lower(),
                        (f, os.path.join(root, f)))

        def harvest_stems(index):
            d = os.path.join(output_folder, f'identity_r{index}')
            if not os.path.isdir(d):
                return None
            return {os.path.splitext(f)[0].lower()
                    for f in os.listdir(d) if f.lower().endswith('.xmp')}

        manifest_paths = []
        for index in range(self.MAX_IDENTITY_COMPONENTS):
            stems_now = harvest_stems(index)
            if not stems_now:  # missing dir or empty harvest = exhaustion
                break
            component_name = f'{scene_name}_c{index}'
            rsalign_path = os.path.join(output_folder, component_name + '.rsalign')
            if not os.path.isfile(rsalign_path):
                self.logger.warning(
                    'Harvest r%d exists but %s was not exported - the '
                    'identity loop ended mid-lap; skipping this manifest',
                    index, os.path.basename(rsalign_path))
                break

            stems_next = harvest_stems(index + 1) or set()
            member_stems = stems_now - stems_next
            if not member_stems:
                self.logger.error(
                    'Successive difference for %s is empty (r%d == r%d) - '
                    'component deletion may not have taken effect; stopping',
                    component_name, index, index + 1)
                break

            members = []
            for stem in sorted(member_stems):
                entry = stem_to_image.get(stem)
                if entry is None:
                    members.append(stem)
                    continue
                members.append(entry[0])
                # Regenerate the displaced calibration-only sidecar
                camera = camera_registry.identify(entry[0])
                if camera is not None:
                    sidecar = os.path.splitext(entry[1])[0] + '.xmp'
                    if not os.path.exists(sidecar):
                        with open(sidecar, 'w', encoding='utf-8') as fh:
                            fh.write(camera_registry.calibration_xmp(camera))

            bbox = component_manifest.bbox_from_flight_log(
                flight_log_path or None, members)
            if flight_log_path and bbox is None:
                self.logger.warning(
                    'No flight-log rows matched the %d member(s) of %s - '
                    'manifest bbox_utm will be null', len(members), component_name)

            manifest = component_manifest.build_manifest(
                zone=scene_name, component=component_name,
                rsalign_path=rsalign_path, images=members, bbox_utm=bbox)
            manifest_paths.append(component_manifest.write_manifest(manifest))
            self.logger.info(
                'Manifest %s: %d camera(s), bbox %s',
                os.path.basename(manifest_paths[-1]), len(members),
                'null' if bbox is None else
                '[%.1f, %.1f, %.1f, %.1f]' % tuple(bbox))

        if not manifest_paths:
            self.logger.error(
                'No usable identity harvests under %s - manifests '
                'unavailable for zone %s', output_folder, scene_name)
        return manifest_paths

    @staticmethod
    def __collect_images(image_folder):
        """All image files under the folder, recursively - a batch zone
        keeps its images in per-camera subfolders."""
        images = []
        for root, _dirs, files in os.walk(image_folder):
            images.extend(f for f in files if f.lower().endswith((".png", ".heif", ".jpg", ".jpeg")))
        return images

    def run(self):
        # Parameters are validated by the orchestrator before run()
        output_dir = os.path.join(self.params['output_dir'].get_value(), "aligned_components")
        display_output = self.params['rs_display_output'].get_value()
        generate_model = self.params['rs_model_generate'].get_value()
        cull_polygons = self.params['rs_model_cull_poly'].get_value()
        texture_model = self.params['rs_model_texture'].get_value()
        simplify_model = self.params['rs_model_simplify'].get_value()

        flight_log_params_path = os.path.join(METADATA_DIR, "FlightLogParams.xml")

        process_data = []

        def queue_folder_to_process(local_input_folder, local_output_dir, local_flight_log_path, local_flight_log_params_path, local_display_output):
            """Queue the folder TREE as one alignment scene.

            RealityScan's -addFolder imports subfolders recursively
            (verified on NA167 zone_13: wca/ + zeuss/ subfolders imported
            into one scene, 93.4% registered), so a zone's per-camera
            subfolders must NOT be queued as separate alignments - doing
            so was splitting every mixed-camera zone into per-camera
            scenes that could never co-register.
            """
            if not os.path.isdir(local_input_folder):
                raise ValueError(f"Input folder {local_input_folder} is not a directory")

            if not self.__collect_images(local_input_folder):
                self.logger.warning(f"No images found under {local_input_folder} - skipping")
                return

            process_data.append({
                'input_folder': local_input_folder,
                'output_dir': local_output_dir,
                'flight_log_path': local_flight_log_path,
                'flight_log_params_path': local_flight_log_params_path,
                'display_output': local_display_output
            })

        # single folder input (not running after batched images module)
        if 'rs_input_image_dir' in self.params:
            input_folder = self.params['rs_input_image_dir'].get_value()
            overall_flight_log_path = self.__get_flight_log_path()

            try:
                queue_folder_to_process(input_folder, output_dir, overall_flight_log_path, flight_log_params_path, display_output)
            except Exception as e:
                self.logger.error(f"Error queueing folder to process: {e}")
        # running after batched images module
        else:
            batch_directory = os.path.join(self.params['output_dir'].get_value(), "batched_images_by_zone")
            if not os.path.isdir(batch_directory):
                self.logger.error(
                    f"Batched images directory not found: {batch_directory}. "
                    "Run the Batch Directory module first (or supply an input "
                    "image folder directly).")
                return {'Success': False}
            batch_folders = [f for f in os.listdir(batch_directory) if os.path.isdir(os.path.join(batch_directory, f))]

            for batch_folder in batch_folders:
                batch_input_folder = os.path.join(batch_directory, batch_folder)
                batch_flight_log_path = self.__get_flight_log_path(batch_input_folder)

                try:
                    queue_folder_to_process(batch_input_folder, output_dir, batch_flight_log_path, flight_log_params_path, display_output)
                except Exception as e:
                    self.logger.error(f"Error queueing folder to process: {e}")

        output_data = {}
        output_data['Success'] = True
        output_data['Output Directory'] = output_dir
        output_data['Component Count'] = len(process_data)
        output_data['Components'] = {}
        output_data['Scenes'] = {}

        if generate_model or cull_polygons or texture_model or simplify_model:
            # Models are generated ONCE, on the merged component, not per
            # zone (per-zone meshes waste GPU-hours on geometry the merge
            # supersedes). See GenerateModel.bat / merge_zones.py.
            self.logger.warning(
                'Model generation flags are ignored during zone alignment; '
                'run the merge workflow and GenerateModel.bat on the merged '
                'component instead.')

        bar = self._initialize_loading_bar(len(process_data), "Aligning Batches")

        # process the data sequentially - each run gets exclusive use of the
        # RealityScan instance (enforced by RealityScanCLI's lock) and the
        # instance is verified to have shut down before the next run starts
        for data in process_data:
            # local names: do not shadow the module-level output_dir above
            input_folder = data['input_folder']
            item_flight_log_path = data['flight_log_path']
            item_flight_log_params_path = data['flight_log_params_path']
            item_display_output = data['display_output']

            # Daily RC_projects save schema: RC_projects one level up from
            # the zone image directory, {label}_{zone}_YYYYMMDD.
            project_label = ''
            if 'rs_project_label' in self.params:
                project_label = (self.params['rs_project_label'].get_value() or '').strip()
            if project_label:
                set_project_save_env(os.path.dirname(os.path.normpath(input_folder)),
                                     project_label)
            else:
                os.environ.pop('RS_PROJECTS_DIR', None)

            # Each zone exports into its own subfolder: components stay
            # importable from their ORIGINAL export location (relocated
            # .rsalign imports hang forever - bug B1) and zones cannot
            # clobber each other's exports.
            zone_name = os.path.basename(os.path.normpath(input_folder))
            zone_output_dir = os.path.join(output_dir, zone_name)
            scene_path = os.path.join(zone_output_dir, zone_name + ".rsproj")

            try:
                component_data, scene_data = self.__align_zone(
                    input_folder, zone_output_dir, zone_name,
                    item_flight_log_path, item_flight_log_params_path,
                    item_display_output)
                output_data['Components'][zone_output_dir] = component_data
                output_data['Scenes'][scene_path] = scene_data
            except Exception as e:
                self.logger.error(f"Error aligning images: {e}")
                # A raising zone must land in the tally as a FAILURE, not
                # vanish from it. Before this, a zone that raised (wedged
                # instance, sidecar OSError after a successful align) was
                # counted neither as succeeded nor failed - nine raising
                # zones out of ten still reported 'Zones Failed: 0' and
                # exit 0 (audit #7, 2026-07-28).
                output_data['Components'][zone_output_dir] = {
                    'Success': False, 'Error': str(e)}

            self._update_loading_bar(bar, 1)

        # Overall success must reflect the per-zone outcomes: this module
        # previously reported Success=True with every zone failed, which
        # made a fully failed alignment run look complete (and exit 0).
        component_results = list(output_data['Components'].values())
        succeeded = sum(1 for c in component_results if c.get('Success'))
        output_data['Zones Succeeded'] = succeeded
        output_data['Zones Failed'] = len(component_results) - succeeded
        if not component_results or succeeded == 0:
            output_data['Success'] = False

        return output_data

    def validate_parameters(self) -> tuple[bool, str | None]:
        success, message = super().validate_parameters()
        if not success:
            return success, message

        if not 'rs_display_output' in self.params:
            return False, 'Display output parameter not found'

        if not 'rs_model_generate' in self.params:
            return False, 'Generate model parameter not found'

        # missing optional params get a real Parameter defaulting to False so
        # run() can still call get_value() on them
        for optional_param in ('rs_model_cull_poly', 'rs_model_texture', 'rs_model_simplify'):
            if optional_param not in self.params:
                self.params[optional_param] = Parameter(
                    name=optional_param, cli_short=None, cli_long=optional_param,
                    type=bool, default_value=False, prompt_user=False)

        # fail fast if RealityScan itself cannot be found
        try:
            executable = self.cli.find_executable()
            self.logger.info(f"Using RealityScan executable: {executable}")
        except FileNotFoundError as e:
            return False, str(e)

        # No overwrite prompt here: zones write into their own subfolders
        # of aligned_components, so other zones' existing exports are
        # expected, and an input() prompt stalls unattended runs (it also
        # crashed with EOFError under a non-interactive stdin). Stale
        # per-zone exports are cleared in __align_zone instead.
        output_dir = os.path.join(self.params['output_dir'].get_value(), 'aligned_components')
        if not os.path.isdir(output_dir):
            os.makedirs(output_dir)

        return True, None
