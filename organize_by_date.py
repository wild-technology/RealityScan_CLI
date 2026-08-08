#!/usr/bin/env python3
"""Sort a folder of survey stills into per-date subdirectories.

Step 1 of the owner's chain (folder organisation). Standalone by design -
it is not a pipeline module; run it before pointing the pipeline at the
imagery.

The date comes from modules.file_metadata_parser.parse_timestamp, the SAME
parser the georeference stage uses, so every filename family the repo's
camera registry knows is recognised. It used to use a local regex anchored
at the START of the name (``^(\\d{8})T\\d{6}``), which matched only the
Sony scheme: on rig imagery every file took the "no date pattern" branch
and the script printed "Complete: 0 files moved" and exited 0
(audit 2026-08-07). Probed then: 'P231C0001_20260807T120000Z.jpg' -> None,
'camlower_20231104020854.jpg' -> None, 'ZEUSS_20260807T120000Z.jpg' -> None.

Usage:
    py -3.13 organize_by_date.py [--source DIR] [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

REPO = os.path.dirname(os.path.realpath(__file__))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from module_base.settings_store import SettingsStore  # noqa: E402
from modules.file_metadata_parser import parse_timestamp  # noqa: E402
from modules.image_exts import ALL_IMAGE_EXTS  # noqa: E402

# The parser's "no timestamp found" sentinel.
_EPOCH = datetime(1970, 1, 1, 0, 0, 0)

# Raw formats the pipeline never reads but an operator still wants sorted.
EXTRA_EXTS = frozenset({'.raw', '.arw'})
IMAGE_EXTENSIONS = frozenset(ALL_IMAGE_EXTS | EXTRA_EXTS)


# The Sony scheme this script was written for: 20250729T155918__DSC7725...
# It has NO trailing 'Z', so the shared parser's `\d{8}T\d{6}Z|\d{14}`
# does not match it. Kept as a documented SECOND pass so widening the
# recognised families never narrows them.
_SONY_TIMESTAMP = re.compile(r'(?<!\d)(\d{8})T\d{6}(?!\d)')


def extract_date_from_filename(filename):
    """Date encoded in the filename, or None.

    Delegates to the shared parser first (leading OR embedded
    ``\\d{8}T\\d{6}Z`` and ``\\d{14}``, plus the legacy cam* prefixes) -
    the same parser the georeference stage uses - then falls back to the
    Z-less Sony form this script originally handled.
    """
    timestamp = parse_timestamp(filename)
    if timestamp != _EPOCH:
        return datetime(timestamp.year, timestamp.month, timestamp.day)
    match = _SONY_TIMESTAMP.search(filename or '')
    if match:
        try:
            return datetime.strptime(match.group(1), '%Y%m%d')
        except ValueError:
            return None
    return None


def get_human_readable_date(dt):
    """
    Convert datetime to human readable format like '29July'
    """
    return dt.strftime('%d%B')


def organize_images_by_date(source_dir, dry_run: bool = False) -> int:
    """Move images into per-date subdirectories. Returns a process exit code.

    Non-zero when nothing moved: "0 files moved" with exit 0 is the
    silence-is-not-success shape - it reads identically whether the folder
    was already organised, held no imagery, or holds imagery this script
    cannot date (audit 2026-08-07). Each of those now says which it is.
    """
    source_path = Path(source_dir)

    if not source_path.is_dir():
        print(f"Error: Directory '{source_dir}' does not exist")
        return 1

    moved_count = 0
    skipped_count = 0
    skipped_example = None
    image_count = 0

    for file_path in sorted(source_path.iterdir()):
        if not (file_path.is_file()
                and file_path.suffix.lower() in IMAGE_EXTENSIONS):
            continue
        image_count += 1
        dt = extract_date_from_filename(file_path.name)

        if dt is None:
            if skipped_example is None:
                skipped_example = file_path.name
            print(f"Skipped (no date pattern): {file_path.name}")
            skipped_count += 1
            continue

        subdir_name = get_human_readable_date(dt)
        target_dir = source_path / subdir_name
        target_path = target_dir / file_path.name

        if dry_run:
            print(f"WOULD MOVE: {file_path.name} -> {subdir_name}/")
            moved_count += 1
            continue

        # Skip rather than overwrite: shutil.move's collision check only
        # fires when the destination is a DIRECTORY, so a same-named file
        # in the date folder was silently replaced (copy2 + unlink of the
        # source). timestamp_rename.py has always handled this correctly;
        # this now matches it (audit 2026-08-07).
        if target_path.exists():
            print(f"SKIP (already in {subdir_name}/): {file_path.name}")
            skipped_count += 1
            continue

        target_dir.mkdir(exist_ok=True)
        shutil.move(str(file_path), str(target_path))
        print(f"Moved: {file_path.name} -> {subdir_name}/")
        moved_count += 1

    print(f"\nComplete: {moved_count} files moved, {skipped_count} files skipped")

    if moved_count:
        return 0
    if image_count == 0:
        print(f"ERROR: no images found directly in {source_dir} "
              f"(looked for {', '.join(sorted(IMAGE_EXTENSIONS))}; "
              "this script does not recurse). Nothing was organised.")
        return 1
    print(f"ERROR: {image_count} image(s) present but NOTHING was moved - "
          f"none of them carries a recognised timestamp (e.g. "
          f"{skipped_example!r}). Expected YYYYMMDDTHHMMSSZ or YYYYMMDDHHMMSS "
          "somewhere in the filename; use timestamp_rename.py first if the "
          "dates are only in EXIF.")
    return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--source', default=None,
                        help='folder containing images to organise by date')
    parser.add_argument('--dry-run', action='store_true',
                        help='print the plan without moving anything')
    args = parser.parse_args(argv)

    settings = SettingsStore()
    # No hardcoded per-user default (hard rule 5: data lives on volumes
    # with user-specific paths). The stored answer from the previous run is
    # offered instead; a first run on a fresh checkout has to be told.
    source_directory = settings.ask(
        "organize_by_date", "source_dir", args.source, None)
    if not source_directory:
        print("ERROR: no source folder. Pass --source DIR (it is remembered "
              "for next time).")
        return 1
    return organize_images_by_date(source_directory, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
