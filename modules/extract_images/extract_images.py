#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import shutil
from datetime import datetime, timedelta

import cv2
import numpy as np

from module_base.rs_module import RSModule
from module_base.parameter import Parameter
from ..file_metadata_parser import _TIMESTAMP_REGEX, parse_timestamp_str, parse_timestamp

# Container formats the extractor accepts. ROV recorders deliver both
# QuickTime (.mov, e.g. Nauticam S231C####_..._chf3_nyx2.mov) and .mp4;
# cv2.VideoCapture reads either.
VIDEO_EXTENSIONS = {'.mp4', '.mov'}

# Split recordings: part files share the recording's START timestamp and
# differ only in a _NNNN_ part counter (S231C0007_20231104020854_0001_...,
# S231C0007_20231104020854_0002_...). Frames in part N start where part
# N-1 ended, NOT at the filename timestamp.
_PART_REGEX = re.compile(
    r'^(?P<prefix>.+?_(?:\d{8}T\d{6}Z|\d{14}))_(?P<part>\d{4})(?P<suffix>_.*)?$')


class ExtractImages(RSModule):
    def __init__(self, logger):
        super().__init__("Extract Images", logger)

    def get_parameters(self) -> dict[str, Parameter]:
        additional_params = {}

        additional_params['image_input_video'] = Parameter(
            name='Input Video File',
            cli_short='i_i',
            cli_long='i_input',
            type=str,
            default_value=None,
            description='Path to the input video file/folder',
            prompt_user=True
        )

        additional_params['image_output_fpm'] = Parameter(
            name='Image Extraction Frames Per Minute',
            cli_short='i_r',
            cli_long='i_output_fpm',
            type=float,
            default_value=1.0,
            description='The number of frames per minute to extract from the video file',
            prompt_user=True
        )

        additional_params['image_output_mpx'] = Parameter(
            name='Output Megapixels',
            cli_short='i_m',
            cli_long='i_mpx',
            type=int,
            default_value=3,
            description='The maximum number of megapixels for the output images',
            prompt_user=True
        )

        return {**super().get_parameters(), **additional_params}

    def __get_video_timestamp_str(self, video_path):
        # Parse the timestamp from the video filename
        video_timestamp_str = parse_timestamp_str(video_path)

        # If the timestamp could not be parsed, raise an error
        if video_timestamp_str == "19700101T000000Z" or video_timestamp_str == "19700101000000":
            raise ValueError("Could not parse timestamp from filename.")

        return video_timestamp_str

    def __get_video_timestamp(self, video_path):
        video_timestamp = parse_timestamp(video_path)

        # If the timestamp could not be parsed, raise an error
        if video_timestamp == datetime(1970, 1, 1, 0, 0, 0):
            raise ValueError("Could not parse timestamp from filename.")

        return video_timestamp

    def __extract_video_cv2(self, video_path, output_folder, output_fpm, output_mpx,
                            start_offset_sec: float = 0.0) -> dict[str, any]:
        """Extract frames at output_fpm, timestamping each output image with
        the wall-clock time of the frame it actually contains.

        The frame READ and the frame TIMESTAMPED must be the same frame:
        the pre-fix code sought to frame N+skip, read it, but stamped it
        with frame N's time, so every image carried a timestamp one output
        interval early (60 s at the default 1 fpm) and georeferencing
        paired it with a position from a minute before it was taken.

        start_offset_sec shifts the whole video in wall-clock time: for
        continuation parts of a split recording the filename carries the
        recording's start, so the part's true start is that timestamp plus
        the summed duration of all earlier parts.
        """
        output_data = {}

        # Attempt to open video file
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            self.logger.error(f"Video file {video_path} could not be opened")
            output_data['Success'] = False
            return output_data

        # Get the video's timestamp
        video_timestamp_str = self.__get_video_timestamp_str(video_path)
        video_timestamp = self.__get_video_timestamp(video_path) + timedelta(seconds=start_offset_sec)

        # Parse the metadata from the video filename
        video_filename = os.path.splitext(os.path.basename(video_path))[0]

        # Video's original frame count and FPS
        video_frame_count = round(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        video_fps = cap.get(cv2.CAP_PROP_FPS)

        if video_fps <= 0 or video_frame_count <= 0:
            self.logger.error(
                f"Video file {video_path} reports no usable FPS/frame count "
                f"(fps={video_fps}, frames={video_frame_count})")
            cap.release()
            output_data['Success'] = False
            return output_data

        # Calculate how many source frames to skip between extractions
        output_fps = output_fpm / 60
        skip_frames = max(1, round(video_fps / output_fps))

        # Frame 0 is included: extraction starts at the video's own timestamp
        frame_numbers = range(0, video_frame_count, skip_frames)

        extracted_count = 0
        bar = self._initialize_loading_bar(len(frame_numbers), "Extracting Frames from Video")

        for frame_number in frame_numbers:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            ret, frame = cap.read()
            if not ret:
                break

            # Timestamp of the frame just read (seconds from video start)
            new_timestamp = video_timestamp + timedelta(seconds=frame_number / video_fps)
            new_timestamp_str = new_timestamp.strftime("%Y%m%dT%H%M%SZ")

            # Index of this extracted frame within its second - nonzero only
            # when extracting more than one frame per second
            fps_int = max(1, round(video_fps))
            frame_index_in_second = int((frame_number % fps_int) // skip_frames)

            # Generate the filename for the current frame by replacing the
            # timestamp in the filename with the new timestamp. Replace the
            # RAW matched substring, not parse_timestamp_str()'s normalized
            # form: for plain 14-digit filenames (e.g. S231C0007_
            # 20231104020854_...) the normalized "...T...Z" form never
            # matches, the replace was a no-op, and every frame of the video
            # overwrote the same output file.
            raw_ts_match = _TIMESTAMP_REGEX.search(video_filename)
            raw_ts = raw_ts_match.group(1) if raw_ts_match else video_timestamp_str
            image_name = video_filename.replace(raw_ts,
                                                new_timestamp_str) + f"_frame{frame_index_in_second}.jpg"
            image_path = os.path.join(output_folder, image_name)

            # compress frame to output_mpx if necessary
            input_height, input_width, _ = frame.shape
            input_mpx = input_height * input_width / 1000000

            if input_mpx > output_mpx:
                output_height = int(input_height * np.sqrt(output_mpx / input_mpx))
                output_width = int(input_width * np.sqrt(output_mpx / input_mpx))
                frame = cv2.resize(frame, (output_width, output_height), interpolation=cv2.INTER_AREA)

            # Save the frame as an image
            cv2.imwrite(image_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            extracted_count += 1

            self._update_loading_bar(bar, 1)

        self._finish_loading_bar(bar)

        cap.release()

        output_data['Success'] = True
        output_data['Input Frame Count'] = video_frame_count
        output_data['Extracted Frame Count'] = extracted_count
        output_data['Input FPM'] = round(video_fps * 60, 1)

        return output_data

    def __video_duration_sec(self, video_path) -> float | None:
        """Duration of a video from its container metadata, or None."""
        cap = cv2.VideoCapture(video_path)
        try:
            if not cap.isOpened():
                return None
            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            fps = cap.get(cv2.CAP_PROP_FPS)
            if fps <= 0 or frame_count <= 0:
                return None
            return frame_count / fps
        finally:
            cap.release()

    def __compute_part_offsets(self, input_path, video_files) -> dict[str, float]:
        """Wall-clock start offsets for continuation parts of split
        recordings. Parts share the recording-start timestamp in their
        filename; part N actually starts after the summed duration of
        parts 1..N-1. Files whose earlier-part durations cannot be read
        are excluded (a wrong timestamp poisons georeferencing silently).
        """
        groups: dict[tuple[str, str], list[tuple[int, str]]] = {}
        for filename in video_files:
            stem = os.path.splitext(filename)[0]
            match = _PART_REGEX.match(stem)
            if match:
                key = (match.group('prefix'), match.group('suffix') or '')
                groups.setdefault(key, []).append((int(match.group('part')), filename))

        offsets = {filename: 0.0 for filename in video_files}
        for key, parts in groups.items():
            if len(parts) < 2:
                continue
            parts.sort()
            cumulative = 0.0
            broken = False
            for index, (part_no, filename) in enumerate(parts):
                if broken:
                    self.logger.error(
                        f"Skipping {filename}: cannot determine its true start "
                        "time because an earlier part of the same recording "
                        "has unreadable duration metadata")
                    offsets.pop(filename, None)
                    continue
                offsets[filename] = cumulative
                if index > 0:
                    self.logger.info(
                        f"Continuation part {filename}: frames offset "
                        f"+{cumulative:.1f}s past the filename timestamp")
                duration = self.__video_duration_sec(os.path.join(input_path, filename))
                if duration is None:
                    broken = True
                else:
                    cumulative += duration
        return offsets

    def run(self):
        # Get parameters (validated by the orchestrator before run())
        input_path = self.params['image_input_video'].get_value()
        output_folder = os.path.join(self.params['output_dir'].get_value(), 'raw_images')
        output_fpm = self.params['image_output_fpm'].get_value()
        output_mpx = self.params['image_output_mpx'].get_value()

        mov_files = []

        if os.path.isfile(input_path):
            # One video file was specified
            # Separate the filename from the path, and add it to the list of video files
            input_video = os.path.basename(input_path)
            mov_files.append(input_video)

            # Set the input path to the directory of the video file
            input_path = os.path.dirname(input_path)
        else:
            # A directory of video files was specified
            mov_files = [filename for filename in os.listdir(input_path) if
                         os.path.splitext(filename)[1].lower() in VIDEO_EXTENSIONS]

        # True start offsets for continuation parts of split recordings
        part_offsets = self.__compute_part_offsets(input_path, mov_files)
        mov_files = [f for f in mov_files if f in part_offsets]

        bar = self._initialize_loading_bar(len(mov_files), "Extracting Videos")

        overall_output_data = {}
        overall_output_data['Success'] = False
        overall_output_data['Total Input Frame Count'] = 0
        overall_output_data['Total Extracted Frame Count'] = 0
        overall_output_data['Output FPM'] = output_fpm
        overall_output_data['Number of Videos'] = len(mov_files)
        overall_output_data['Videos'] = {}

        for mov_file in mov_files:
            mov_path = os.path.join(input_path, mov_file)
            file_extension = os.path.splitext(mov_path)[1].lower()

            if not os.path.isfile(mov_path) or file_extension not in VIDEO_EXTENSIONS:
                continue

            individual_output_data = self.__extract_video_cv2(
                mov_path, output_folder, output_fpm, output_mpx,
                start_offset_sec=part_offsets.get(mov_file, 0.0))
            self._update_loading_bar(bar, 1)

            if individual_output_data is not None and individual_output_data.get('Success') == True:
                overall_output_data['Success'] = True
                overall_output_data['Total Input Frame Count'] += individual_output_data['Input Frame Count']
                overall_output_data['Total Extracted Frame Count'] += individual_output_data['Extracted Frame Count']
                overall_output_data['Videos'][mov_path] = individual_output_data
            else:
                self.logger.error(f'Failed to extract video: {mov_path}')

        return overall_output_data

    def validate_parameters(self) -> tuple[bool, str | None]:
        success, message = super().validate_parameters()
        if not success:
            return success, message

        if not 'image_input_video' in self.params:
            return False, 'Input video parameter not found'

        if not 'output_dir' in self.params:
            return False, 'Output directory parameter not found'

        if not 'image_output_fpm' in self.params:
            return False, 'Output FPM parameter not found'

        if not 'image_output_mpx' in self.params:
            return False, 'Output MPX parameter not found'

        input_video = self.params['image_input_video'].get_value()
        is_input_folder = os.path.isdir(input_video)

        output_dir = os.path.join(self.params['output_dir'].get_value(), 'raw_images')
        output_fpm = self.params['image_output_fpm'].get_value()
        output_mpx = self.params['image_output_mpx'].get_value()

        # input path is either a single video file or a folder of video files
        if is_input_folder:
            videos = [f for f in os.listdir(input_video)
                      if os.path.splitext(f)[1].lower() in VIDEO_EXTENSIONS]
            if not videos:
                return False, f'Input folder contains no video files ({"/".join(sorted(VIDEO_EXTENSIONS))})'
        else:
            if not os.path.isfile(input_video):
                return False, 'Input file does not exist'

            if os.path.splitext(input_video)[1].lower() not in VIDEO_EXTENSIONS:
                return False, f'Input path is not a video file ({"/".join(sorted(VIDEO_EXTENSIONS))})'

        if os.path.isdir(output_dir) and os.listdir(output_dir):
            self.logger.warning('Extracted images folder already exists. Overwrite? (y/n)')
            # EOF-safe, refusing the DESTRUCTIVE branch: a bare input()
            # raised EOFError out of validate_parameters on any unattended
            # run (Windows trap registry: isatty() lies under hidden
            # consoles). It failed closed, so this is robustness, not a
            # loss path - same pattern as batch_directory's identical
            # prompt (audit 2026-08-07).
            try:
                overwrite = input()
            except EOFError:
                return False, ('Extracted images folder already exists and '
                               'this run is non-interactive - refusing to '
                               'overwrite it. Delete it yourself, or point '
                               '--output_dir somewhere else.')

            if overwrite.strip().lower() != 'y':
                return False, 'Extracted images folder not created'
            else:
                shutil.rmtree(output_dir)

        if not os.path.isdir(output_dir):
            os.makedirs(output_dir)

        if output_fpm <= 0:
            return False, 'Output FPM must be greater than 0'

        if output_mpx <= 0:
            return False, 'Output MPX must be greater than 0'

        return True, None
