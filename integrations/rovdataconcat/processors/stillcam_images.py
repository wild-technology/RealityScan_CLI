# processors/stillcam_images.py
from pathlib import Path
import pandas as pd
from PIL import Image
from datetime import datetime

from .report import RunReport

def process_data(root_dir):
    """
    Processes merged Sealog CSV files to locate camera image filenames,
    then extracts and converts those PNG images into 1280x720 JPEGs
    at ~80% quality.

    * Searches for <dive_number> folders in 'RUMI_processed/'
    * Looks for '*_merged.csv' in each dive folder
    * Extracts the PNG path from 'vehicleRealtimeDualHDGrabData.filename_value'
    * Parses the timestamp from the filename to locate the actual PNG in:
         processed/capture_pngs/capture_YYYYMMDD/<filename>.png
    * Resizes the image to 1280x720, saves as .jpg (80% quality) in:
         RUMI_processed/<dive_number>/stillcam_images/

    After all dives are processed, a summary is displayed showing:
      - How many CSV files were examined
      - How many total rows had PNG references
      - How many source PNG files were missing
      - How many parse/conversion errors occurred
      - How many images were successfully converted

    Parameters
    ----------
    root_dir : Path or str
        Root directory containing the expedition data
    """
    # Convert root_dir to Path object if it's a string
    root_dir = Path(root_dir)
    rumi_processed_dir = root_dir / "RUMI_processed"

    if not rumi_processed_dir.exists():
        print(f"'{rumi_processed_dir}' not found; nothing to process.")
        return

    # Counters for final summary
    total_csvs_examined = 0
    total_rows_examined = 0
    total_png_references = 0
    total_missing_pngs = 0
    total_parse_errors = 0
    total_converted = 0
    total_already_done = 0

    # Iterate over each dive folder in RUMI_processed
    for dive_path in rumi_processed_dir.iterdir():
        if not dive_path.is_dir():
            continue

        # Find all merged CSV files in this dive folder
        csv_files = list(dive_path.glob("*_merged.csv"))
        if not csv_files:
            continue

        for csv_path in csv_files:
            total_csvs_examined += 1
            print(f"\n[Stillcam] Processing merged CSV: {csv_path}")
            try:
                df = pd.read_csv(csv_path)
            except Exception as e:
                print(f"  Error reading '{csv_path}': {e}")
                continue

            filename_col = "vehicleRealtimeDualHDGrabData.filename_value"
            if filename_col not in df.columns:
                print(f"  Column '{filename_col}' not found. Skipping.")
                continue

            # Create an output dir for stillcam images, e.g. RUMI_processed/<dive>/stillcam_images/
            stillcam_dir = dive_path / "stillcam_images"
            stillcam_dir.mkdir(exist_ok=True)

            # Process each row that has a PNG path
            for idx, row in df.iterrows():
                total_rows_examined += 1
                png_path = row.get(filename_col, "")
                if not isinstance(png_path, str) or not png_path.lower().endswith(".png"):
                    continue

                total_png_references += 1

                # e.g. /data/sealog-vehicle-files/images/cam1_20231031185717.png
                png_path_obj = Path(png_path)
                basename = png_path_obj.name

                # Attempt to parse the datetime from the filename's last underscore
                # e.g. "cam1_20231031185717.png" -> "20231031185717"
                try:
                    datetime_part = basename.split("_")[-1].replace(".png", "")
                    dt = datetime.strptime(datetime_part, "%Y%m%d%H%M%S")
                except ValueError:
                    total_parse_errors += 1
                    print(f"  Could not parse datetime from filename: {basename}")
                    continue

                # Build the source PNG path under processed/capture_pngs/capture_YYYYMMDD/<basename>
                date_subdir = dt.strftime("capture_%Y%m%d")
                source_png_path = root_dir / "processed" / "capture_pngs" / date_subdir / basename

                if not source_png_path.exists():
                    total_missing_pngs += 1
                    print(f"  Source PNG not found: {source_png_path}")
                    continue

                # Resume support: skip images already converted in a prior run.
                jpg_name = png_path_obj.stem + ".jpg"
                jpg_path = stillcam_dir / jpg_name
                if jpg_path.exists():
                    total_already_done += 1
                    continue

                # Convert the PNG to 1280x720 JPEG (80% quality)
                try:
                    with Image.open(source_png_path) as img:
                        img = img.resize((1280, 720), Image.Resampling.LANCZOS)
                        img.save(jpg_path, "JPEG", quality=80)
                        total_converted += 1
                        print(f"  Saved resized image: {jpg_path}")
                except Exception as e:
                    total_parse_errors += 1
                    print(f"  Error converting {source_png_path}: {e}")

    # Final summary after all dives
    print("\n------------------ Stillcam Summary ------------------")
    print(f"  CSV files examined:        {total_csvs_examined}")
    print(f"  Total rows examined:       {total_rows_examined}")
    print(f"  Total PNG references:      {total_png_references}")
    print(f"  Missing PNG files:         {total_missing_pngs}")
    print(f"  Parse/Conversion errors:   {total_parse_errors}")
    print(f"  Already converted (skip):  {total_already_done}")
    print(f"  Successfully converted:    {total_converted}")
    print("------------------------------------------------------\n")

    report = RunReport("stillcam_images", rumi_processed_dir)
    report.metric("png_references", total_png_references)
    report.metric("converted", total_converted)
    report.metric("skipped_already_done", total_already_done)
    if total_missing_pngs:
        report.warn("missing-source",
                    f"{total_missing_pngs} referenced PNGs not found under processed/capture_pngs")
    if total_parse_errors:
        report.warn("conversion-errors",
                    f"{total_parse_errors} filenames failed to parse or convert")
    report.finalize()
