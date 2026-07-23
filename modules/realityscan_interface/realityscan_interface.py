from __future__ import annotations

import os
import shutil

from module_base.rs_module import RSModule
from module_base.parameter import Parameter
from ..file_metadata_parser import parse_timestamp, parse_timestamp_str, parse_frame_number, parse_frame_number_str
from ..flight_logs import (find_flight_log, utm_zone_from_flight_log_name,
                           write_flight_log_params)
from .realityscan_cli import RealityScanCLI, METADATA_DIR

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

    def __align_images(self, input_folder, output_folder, component_file_name, flight_log_path, flight_log_params_path, display_output=False, generate_model=True, cull_polygons=False, texture_model=False, simplify_model=False):
        """
        Aligns images in a folder and saves the component file to the output folder.

        All RealityScan execution goes through RealityScanCLI, which handles
        instance locking, progress monitoring, error detection, and verified
        instance shutdown (see realityscan_cli.py).
        """

        if not input_folder:
            raise ValueError("Input folder is not specified")

        if not os.path.isdir(input_folder):
            raise ValueError(f"Input folder {input_folder} is not a directory")

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

        log_dir = os.path.join(os.path.dirname(output_folder), "logs")

        # The params XML declares the trajectory's coordinate system. The
        # template's zone belongs to whatever cruise last edited it, so
        # regenerate it from the zone tag in the flight log's own filename
        # (flight_log_53N_UTM.txt -> EPSG:32653) whenever possible.
        if flight_log_path and flight_log_params_path:
            zone_band = utm_zone_from_flight_log_name(flight_log_path)
            if zone_band is not None:
                zone, band = zone_band
                generated = os.path.join(log_dir, f'FlightLogParams_{zone}{band}.xml')
                flight_log_params_path = write_flight_log_params(
                    flight_log_params_path, generated, zone, band)
                self.logger.info(f'Flight log CRS: UTM zone {zone}{band} '
                                 f'(params: {generated})')
            else:
                self.logger.warning(
                    f'Flight log "{os.path.basename(flight_log_path)}" carries no '
                    'UTM zone tag - using the params template as-is. Verify its '
                    'coordinate system matches this cruise!')

        generate_model_str = "true" if generate_model else "false"
        cull_polygons_str = "true" if cull_polygons else "false"
        texture_model_str = "true" if texture_model else "false"
        simplify_model_str = "true" if simplify_model else "false"

        # Snapshot the output folder so newly exported component files can be
        # identified regardless of what RealityScan names them (exports are
        # named after the component, e.g. "Merged.rsalign", and earlier
        # batches' renamed components already live in this folder).
        files_before = set(os.listdir(output_folder))

        result = self.cli.run_batch_script(
            'AlignImagesFromFolder.bat',
            [input_folder, output_folder, flight_log_path, flight_log_params_path,
             generate_model_str, cull_polygons_str, component_file_name,
             texture_model_str, simplify_model_str],
            log_dir, display_output)

        if not result.success:
            self.logger.error(f"RealityScan workflow failed for {input_folder}: "
                              f"{result.errors or f'exit code {result.return_code}'} (log: {result.log_path})")
            return {'Success': False, 'Component Count': 0}, {'Success': False}

        generated_component_files = [f for f in os.listdir(output_folder)
                                     if f not in files_before and f.endswith(COMPONENT_EXTENSIONS)]
        component_path_base = os.path.join(output_folder, component_file_name)

        outputted_component_count = 0

        if not generated_component_files or len(generated_component_files) == 0:
            return {'Success': False, 'Component Count': 0}, {'Success': False}

        # use index for loop so we can index the name
        for index, generated_component_file in enumerate(generated_component_files):
            generated_component_path = os.path.join(output_folder, generated_component_file)
            extension = os.path.splitext(generated_component_file)[1]

            # Never prompt mid-run (an unattended multi-hour pipeline would
            # stall) and never overwrite: skip to the next free index.
            suffix = index
            component_path = f"{component_path_base}_{suffix}{extension}"
            while os.path.exists(component_path):
                suffix += 1
                component_path = f"{component_path_base}_{suffix}{extension}"
            if suffix != index:
                self.logger.warning(
                    'Component "%s_%d%s" already exists (previous run?); '
                    'saving as "%s" instead', component_path_base, index,
                    extension, os.path.basename(component_path))

            os.rename(generated_component_path, component_path)
            outputted_component_count += 1

        # The workflow saves the project directly as <component name>.rsproj
        # in the output folder; verify it actually exists and is non-empty
        # instead of trusting the workflow's exit status alone.
        scene_success = False
        for extension in SCENE_EXTENSIONS:
            scene_file = f"{component_path_base}{extension}"
            if os.path.isfile(scene_file) and os.path.getsize(scene_file) > 0:
                scene_success = True
                break

        if not scene_success:
            self.logger.error(f'Project file "{component_path_base}.rsproj" was not created')

        component_data = {}
        component_data['Success'] = True
        component_data['Component Count'] = outputted_component_count

        scene_data = {}
        scene_data['Success'] = scene_success
        return component_data, scene_data

    @staticmethod
    def __collect_images(image_folder):
        """All image files under the folder, recursively - a batch zone
        keeps its images in per-camera subfolders."""
        images = []
        for root, _dirs, files in os.walk(image_folder):
            images.extend(f for f in files if f.lower().endswith((".png", ".heif", ".jpg", ".jpeg")))
        return images

    def __get_component_file_name(self, image_folder):
        """
        Gets the name of the component output file for a folder of images based on the start and end frame files.
        """

        if image_folder is None or not os.path.isdir(image_folder):
            raise ValueError("Image folder is not specified or is invalid")

        files = self.__collect_images(image_folder)
        files.sort(key=lambda x: (parse_timestamp(x), parse_frame_number(x)))

        start_file = files[0]
        end_file = files[-1]

        start_timestamp = parse_timestamp_str(start_file)
        end_timestamp = parse_timestamp_str(end_file)

        timestamp_segment = f"{start_timestamp}-{end_timestamp}"

        component_metadata_ext = start_file.replace(start_timestamp, timestamp_segment)
        component_metadata_ext = component_metadata_ext.replace(f"_frame{parse_frame_number_str(start_file)}", "")
        component_metadata = os.path.splitext(component_metadata_ext)[0]

        return component_metadata

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
                'component_file_name': self.__get_component_file_name(local_input_folder),
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

        bar = self._initialize_loading_bar(len(process_data), "Aligning Batches")

        # process the data sequentially - each run gets exclusive use of the
        # RealityScan instance (enforced by RealityScanCLI's lock) and the
        # instance is verified to have shut down before the next run starts
        for data in process_data:
            # local names: do not shadow the module-level output_dir above
            input_folder = data['input_folder']
            item_output_dir = data['output_dir']
            component_file_name = data['component_file_name']
            item_flight_log_path = data['flight_log_path']
            item_flight_log_params_path = data['flight_log_params_path']
            item_display_output = data['display_output']

            component_path = os.path.join(item_output_dir, component_file_name)
            scene_path = os.path.join(item_output_dir, component_file_name + ".rsproj")

            try:
                component_data, scene_data = self.__align_images(input_folder, item_output_dir, component_file_name, item_flight_log_path, item_flight_log_params_path, item_display_output, generate_model, cull_polygons, texture_model, simplify_model)
                output_data['Components'][component_path] = component_data
                output_data['Scenes'][scene_path] = scene_data
            except Exception as e:
                self.logger.error(f"Error aligning images: {e}")

            self._update_loading_bar(bar, 1)

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

        # Validate output directory
        output_dir = os.path.join(self.params['output_dir'].get_value(), 'aligned_components')

        # if the output directory already exists and it's not empty, ask the user if they want to overwrite it
        if os.path.isdir(output_dir) and os.listdir(output_dir):
            self.logger.warning('Aligned components folder already exists. Overwrite? (y/n)')
            overwrite = input()

            if overwrite.strip().lower() != 'y':
                return False, 'Aligned components folder not created'
            else:
                shutil.rmtree(output_dir)

        if not os.path.isdir(output_dir):
            os.makedirs(output_dir)

        return True, None
