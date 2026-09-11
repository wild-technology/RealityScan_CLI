#!/usr/bin/env python3
"""
Expedition Data Processing Orchestrator (v2) -- fixed pathing, non-interactive

Runs all modules automatically, aborts on first error.
Processed output directory: <root_dir>/RUMI_processed
"""

import argparse
import logging
import sys
from pathlib import Path

# Processor imports
import processors.dive_summaries as dive_summaries
import processors.process_dat as process_dat
import processors.usbl_sdyn as sdyn_usbl
import processors.sensors_sealog as sensors_sealog
import processors.stillcam_images as stillcam_images
from processors.report import stage_status, stage_completed_ok

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

DEFAULT_RAW_DIR = Path("Z:/NA173")


def get_directories(cli_dir=None):
    """
    Resolve the raw data directory (root_dir), from the CLI argument if given,
    otherwise interactively. The processed directory is fixed to
    <root_dir>/RUMI_processed.
    """
    logging.debug("Entered get_directories()")
    default_dir = DEFAULT_RAW_DIR

    if cli_dir is not None:
        root_dir = Path(cli_dir)
        if not root_dir.is_dir():
            raise SystemExit(f"Error: The directory '{root_dir}' does not exist.")
    else:
        print("Where is your raw data located?")
        raw_input_val = input(f"Enter the path to the directory containing raw data [default: {default_dir}]: ").strip()
        root_dir = Path(raw_input_val) if raw_input_val else default_dir

    while not root_dir.is_dir():
        logging.debug(f"Directory '{root_dir}' does not exist.")
        print(f"Error: The directory '{root_dir}' does not exist. Please try again.")
        raw_input_val = input(f"Enter the path to the directory containing raw data [default: {default_dir}]: ").strip()
        logging.debug(f"User re-input for raw data directory: '{raw_input_val}'")
        root_dir = Path(raw_input_val) if raw_input_val else default_dir

    processed_dir = root_dir / "RUMI_processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    logging.debug(f"Processed data directory created or verified: {processed_dir}")

    print(f"\n  * Raw data directory:     {root_dir}")
    print(f"  * Processed data folder:  {processed_dir}")

    logging.debug("Exiting get_directories()")
    return root_dir, processed_dir


# Restart support. A step counts as done only when its JSON provenance
# sidecar (RUMI_processed/reports/<step>.json) records a clean completed run.
#
# This used to glob for any ONE output file, which made resume step-granular
# while the outputs are dive-granular: these steps parse every raw file once
# and then write per dive, so a run that died partway through the dive loop
# left the first dive's CSV behind and the next run skipped the whole step --
# silently shipping an expedition missing every dive after the failure.
# finalize() is the only thing that writes a sidecar, so a crash or an early
# error return now correctly leaves the step unfinished.
#
# stillcam_images is deliberately absent: it resumes per image internally and
# must run every time so newly arrived captures are picked up.
RESUMABLE_STEPS = ("dive_summaries", "process_dat", "usbl_sdyn", "sensors_sealog")


def step_completed(name, root_dir):
    """True when `name` recorded a clean completed run in an earlier invocation."""
    if name not in RESUMABLE_STEPS:
        return False
    return stage_completed_ok(Path(root_dir) / "RUMI_processed", name)


def run_step(script_module, root_dir, force=False) -> str:
    """
    Run script_module.process_data(root_dir).
    Returns 'ok', 'skipped', or 'failed'.
    """
    name = script_module.__name__.split('.')[-1]
    if not force and step_completed(name, root_dir):
        print(f"\n[resume] {name}: completed cleanly in an earlier run -- skipping "
              f"(rerun with --force to regenerate).")
        return "skipped"
    logging.debug(f"Starting {name}")
    print(f"\nProcessing {name}...")
    try:
        script_module.process_data(root_dir)
    except Exception as e:
        logging.exception(f"{name} failed")
        print(f"\nERROR in {name}: {e}\nAborting subsequent steps.")
        return "failed"

    # Returning normally is not success. Every processor guards its inputs with
    # bare `return`s that fire before its RunReport exists, so a missing input
    # or an unreadable summary file exits process_data() quietly -- which this
    # function used to report as "done", letting the pipeline continue on absent
    # data and exit 0.
    status = stage_status(Path(root_dir) / "RUMI_processed", name)
    if status is None:
        print(f"\nERROR in {name}: finished without writing its data quality "
              f"report, so it exited on an error path before doing any work. "
              f"Check the messages above.\nAborting subsequent steps.")
        return "failed"
    if status == "error":
        print(f"\nERROR in {name}: its data quality report records errors "
              f"(see the report block above).\nAborting subsequent steps.")
        return "failed"

    print(f"Finished {name}.")
    logging.debug(f"Finished {name}")
    return "ok"


def main():
    parser = argparse.ArgumentParser(description="ROV raw data extraction pipeline (stage 1)")
    parser.add_argument("--dir", help="Raw data root directory (skips the interactive prompt)")
    parser.add_argument("--force", action="store_true",
                        help="Rerun every step even if its outputs already exist")
    args = parser.parse_args()

    logging.debug("Starting main()")
    print("--------------------------------------------------")
    print("     Expedition Data Processing Orchestrator (v2) ")
    print("--------------------------------------------------")

    # 1) Get directories
    root_dir, processed_dir = get_directories(args.dir)
    logging.debug(f"Directories set. Root: {root_dir}, Processed: {processed_dir}")

    steps = [
        ("Dive Summaries", dive_summaries),
        ("Combined .DAT Processing (OCT + VFR)", process_dat),
        ("USBL Lat/Long Uncertainty", sdyn_usbl),
        ("Sealog Sensor Data", sensors_sealog),
        ("Convert StillCam PNGs to JPGs", stillcam_images),
    ]

    statuses = {}
    for idx, (title, module) in enumerate(steps, start=1):
        print(f"\n[ Step {idx} ]: {title}")
        status = run_step(module, root_dir, force=args.force)
        statuses[module.__name__.split('.')[-1]] = status
        if status == "failed":
            break

        # Downstream steps need the dive summaries file regardless of whether
        # the step ran or was skipped on resume.
        if module is dive_summaries:
            summary_file = processed_dir / "all_dive_summaries.csv"
            if not summary_file.exists():
                print(f"\nError: {summary_file} was not created. "
                      f"Cannot continue with .DAT processing.")
                statuses[module.__name__.split('.')[-1]] = "failed"
                break
            print(f"\nDive summaries present: {summary_file}")

    print("\n--------------------------------------------------")
    print("Run summary:")
    for name, status in statuses.items():
        marker = {"ok": "done", "skipped": "skipped (resume)", "failed": "FAILED"}[status]
        print(f"  {name:20s} {marker}")
    if any(s == "failed" for s in statuses.values()):
        print("Pipeline aborted at the failed step. Fix the issue and rerun --")
        print("completed steps will be skipped automatically (use --force to redo).")
    else:
        print(f"Outputs in: '{processed_dir}'")
    print("--------------------------------------------------")
    logging.debug("Exiting main()")
    # Non-zero on failure so a caller can tell; previously always 0.
    return 1 if any(s == "failed" for s in statuses.values()) else 0


if __name__ == "__main__":
    logging.debug("Script started")
    _rc = main()
    logging.debug("Script finished")
    sys.exit(_rc)
