#!/usr/bin/env python3
"""Decimate a folder of images: copy an evenly spaced percentage to a new
folder (dataset thinning). Never touches the source files.

Two ways to run it:

    py -3.13 decimator.py --source <dir> --dest <dir> --keep 20 --yes
    py -3.13 decimator.py            (interactive; answers are remembered)

Unattended runs MUST pass --yes: the copy is a write into a folder the
operator named, so an EOF stdin cancels instead of proceeding. Until
2026-09-05 this script had no argument parser and a bare input() loop that
spun forever on an EOF stdin.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import List

try:
    from module_base.settings_store import SettingsStore
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
    from module_base.settings_store import SettingsStore

KEEP_CHOICES = (10, 20, 30, 40, 50)
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.gif'}


def get_image_files(directory: Path) -> List[Path]:
    """All image files directly under ``directory``, sorted by name."""
    return sorted(f for f in directory.iterdir()
                  if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS)


def get_valid_directory(settings: SettingsStore, key: str, prompt: str,
                        must_exist: bool = True) -> Path:
    """Prompt for a directory and validate it; the last answer is the
    default. Under an unattended run the store raises by name instead of
    prompting (SettingsStore._input_or_default)."""
    while True:
        path_str = settings.prompt("decimator", key, prompt)
        path = Path(path_str).expanduser().resolve()
        if must_exist and not path.is_dir():
            print(f"Error: not an existing directory: {path}")
            continue
        return path


def get_decimation_ratio(settings: SettingsStore) -> int:
    """Interactive ratio choice; the last choice is the default."""
    print("\nSelect decimation ratio (percentage of images to keep):")
    for i, pct in enumerate(KEEP_CHOICES, 1):
        print(f"  {i}) {pct}%")
    while True:
        try:
            choice = int(settings.prompt("decimator", "decimation_choice",
                                         "Enter choice (1-5)"))
        except ValueError:
            print("Error: Please enter a valid number")
            continue
        if 1 <= choice <= len(KEEP_CHOICES):
            return KEEP_CHOICES[choice - 1]
        print(f"Error: Please enter a number between 1 and {len(KEEP_CHOICES)}")


def select_images_to_copy(image_files: List[Path], keep_percentage: int) -> List[Path]:
    """Evenly spaced subset keeping ``keep_percentage`` of the files."""
    total_images = len(image_files)
    num_to_keep = round(total_images * keep_percentage / 100)
    if num_to_keep >= total_images:
        return list(image_files)
    if num_to_keep <= 0:
        return []
    step = total_images / num_to_keep
    selected_indices = [round(i * step) for i in range(num_to_keep)]
    return [image_files[i] for i in selected_indices if i < total_images]


def copy_images(source_files: List[Path], destination_dir: Path) -> int:
    """Copy the selection; returns how many landed."""
    destination_dir.mkdir(parents=True, exist_ok=True)
    copied_count = 0
    for source_file in source_files:
        try:
            shutil.copy2(source_file, destination_dir / source_file.name)
            copied_count += 1
        except OSError as exc:
            print(f"Warning: Failed to copy {source_file.name}: {exc}")
    return copied_count


def print_summary(original_count: int, selected_count: int,
                  keep_percentage: int, source_dir: Path, dest_dir: Path) -> None:
    print("\n" + "=" * 60)
    print("DECIMATION SUMMARY")
    print("=" * 60)
    print(f"Source directory:       {source_dir}")
    print(f"Destination directory:  {dest_dir}")
    print(f"Original image count:   {original_count}")
    print(f"Decimation ratio:       {keep_percentage}%")
    print(f"Images to copy:         {selected_count}")
    print(f"Images to skip:         {original_count - selected_count}")
    print("=" * 60)


def confirm_operation(assume_yes: bool) -> bool:
    """Yes/no gate. ``--yes`` is the ONLY unattended path that proceeds;
    an EOF stdin cancels."""
    if assume_yes:
        return True
    while True:
        try:
            response = input("\nProceed with copy operation? (yes/no): ").strip().lower()
        except EOFError:
            print("Non-interactive run and no --yes: operation cancelled, "
                  "nothing copied.")
            return False
        if response in ('yes', 'y'):
            return True
        if response in ('no', 'n'):
            return False
        print("Please enter 'yes' or 'no'")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--source', default=None,
                        help='folder of images to thin (prompted when omitted)')
    parser.add_argument('--dest', default=None,
                        help='destination folder, created if missing '
                             '(prompted when omitted)')
    parser.add_argument('--keep', type=int, default=None, choices=KEEP_CHOICES,
                        help='percentage of images to keep (prompted when omitted)')
    parser.add_argument('--yes', '-y', action='store_true',
                        help='proceed without the confirmation prompt')
    return parser


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    print("Image Decimation Tool")
    print("=" * 60)
    settings = SettingsStore()

    if args.source:
        source_dir = Path(args.source).expanduser().resolve()
        if not source_dir.is_dir():
            print(f"Error: --source is not an existing directory: {source_dir}")
            return 1
        settings.set("decimator", "source_dir", str(source_dir))
    else:
        source_dir = get_valid_directory(
            settings, "source_dir", "\nEnter path to source image folder")

    print(f"\nScanning for images in: {source_dir}")
    image_files = get_image_files(source_dir)
    if not image_files:
        print("Error: No image files found in source directory")
        return 1
    print(f"Found {len(image_files)} image files")

    keep_percentage = args.keep or get_decimation_ratio(settings)

    if args.dest:
        dest_dir = Path(args.dest).expanduser().resolve()
        settings.set("decimator", "dest_dir", str(dest_dir))
    else:
        dest_dir = get_valid_directory(
            settings, "dest_dir", "\nEnter path to destination folder",
            must_exist=False)

    selected_images = select_images_to_copy(image_files, keep_percentage)
    print_summary(len(image_files), len(selected_images), keep_percentage,
                  source_dir, dest_dir)
    if not confirm_operation(args.yes):
        print("\nOperation cancelled by user")
        return 1

    print("\nCopying images...")
    copied_count = copy_images(selected_images, dest_dir)
    print(f"\nOperation complete: {copied_count} images copied successfully")
    if copied_count < len(selected_images):
        print(f"Warning: {len(selected_images) - copied_count} images failed to copy")
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user")
        sys.exit(130)
