from pathlib import Path
import argparse
import sys
import importlib

def prompt_directory(prompt, default=None, must_exist=True):
    """
    Prompts the user for a directory, using a default if no input is given.
    If must_exist is True, the prompt repeats until the provided directory exists.
    """
    while True:
        if default is not None:
            response = input(f"{prompt} [default: {default}]: ").strip()
            path = Path(response) if response else Path(default)
        else:
            response = input(f"{prompt}: ").strip()
            path = Path(response)
        if must_exist and not path.is_dir():
            print(f"Error: The directory '{path}' does not exist. Please try again.")
        else:
            return path.resolve()

def get_directories(args):
    """Resolve base, expedition, dive (from CLI args or prompts); use
    RUMI_processed as canonical root.
    Structure:
      processed_dir = <base>/<EXPEDITION>/RUMI_processed/<DIVE>
      raw_dir = processed_dir  # inputs live here as well
    """
    default_base = Path("Z:/")
    if args.base:
        base_dir = Path(args.base)
        if not base_dir.is_dir():
            sys.exit(f"Error: The base directory '{base_dir}' does not exist.")
    else:
        base_dir = prompt_directory("Enter the base directory containing expeditions", default_base)

    expedition = (args.expedition or "").strip()
    while not expedition:
        expedition = input("Enter the expedition (e.g., NA173): ").strip()
        if not expedition:
            print("Error: Expedition cannot be empty.")

    dive = (args.dive or "").strip()
    while not dive:
        dive = input("Enter the dive folder (e.g., H2075): ").strip()
        if not dive:
            print("Error: Dive folder cannot be empty.")

    processed_dir = (base_dir / expedition / "RUMI_processed" / dive).resolve()
    if not processed_dir.is_dir():
        print(f"Error: The dive folder '{processed_dir}' does not exist.")
        sys.exit(1)

    raw_dir = processed_dir  # keep module signatures, but point at processed_dir

    print(f"\n  * Expedition: {expedition}")
    print(f"  * Dive: {dive}")
    print(f"  * Data directory (raw_dir): {raw_dir}")
    print(f"  * Processed directory:      {processed_dir}")
    return raw_dir, processed_dir

# Restart support: the file each stage produces (used to detect completed
# work) and the stage's primary input file (used to detect STALE outputs --
# an output older than its input means the input was regenerated after the
# output was written, so skipping the stage would ship mismatched data).
# "input" may name one file or several; a stage is stale when its output is
# older than the NEWEST of the inputs that exist.
#
# kalman_concat used to declare "input": None ("it has no single input file"),
# and that quietly broke the whole chain. Its output is kalman_filter's
# declared input, so if kalman_concat never reruns, filtered_datatable.csv's
# mtime never advances, final_datatable.csv is never older than it, and
# neither are assess/offset downstream. Stage 2 was therefore a ONE-SHOT per
# dive: rerunning stage 1 with --force to correct nav and then rerunning
# stage 2 printed four "[resume] skipping" lines and exited 0 while keeping
# every stale output. Listing the four stage-1 files it actually reads
# (kalman_concat.py:66-69) restores the chain at its root.
MODULE_OUTPUTS = {
    "kalman_concat": {"output": "{exp}_{dive}_filtered_datatable.csv",
                      "input": ["{exp}_{dive}_USBL_Hercules.csv",
                                "{exp}_{dive}_pitch_roll_heading_octans.csv",
                                "{exp}_{dive}_dvl_lat_long.csv",
                                "{exp}_{dive}_sealog_sensors_merged.csv"]},
    "kalman_filter": {"output": "{exp}_{dive}_final_datatable.csv",
                      "input": "{exp}_{dive}_filtered_datatable.csv"},
    "kalman_assess": {"output": "{exp}_{dive}_kalman_assessment.csv",
                      "input": "{exp}_{dive}_kalman_filtered_data.csv"},
    "kalman_offset": {"output": "{exp}_{dive}_filtered_offset_final.csv",
                      "input": "{exp}_{dive}_final_datatable.csv"},
}


def _module_paths(module_name, processed_dir, kind):
    """Every path declared for `kind`, as a list (empty when none declared)."""
    dive = processed_dir.name
    exp = processed_dir.parent.parent.name
    entry = MODULE_OUTPUTS.get(module_name)
    if not entry:
        return []
    pattern = entry.get(kind)
    if not pattern:
        return []
    patterns = [pattern] if isinstance(pattern, str) else list(pattern)
    return [processed_dir / pat.format(exp=exp, dive=dive) for pat in patterns]


def _module_path(module_name, processed_dir, kind):
    paths = _module_paths(module_name, processed_dir, kind)
    return paths[0] if paths else None


def module_output_path(module_name, processed_dir):
    return _module_path(module_name, processed_dir, "output")


def module_input_path(module_name, processed_dir):
    """The stage's primary (first-declared) input; see module_input_paths."""
    return _module_path(module_name, processed_dir, "input")


def module_input_paths(module_name, processed_dir):
    """Every input the stage reads -- the set the freshness check compares."""
    return _module_paths(module_name, processed_dir, "input")


def newest_existing_input(module_name, processed_dir):
    """(path, mtime) of the most recently modified declared input that exists."""
    newest = None
    for path in module_input_paths(module_name, processed_dir):
        if path.exists():
            mtime = path.stat().st_mtime
            if newest is None or mtime > newest[1]:
                newest = (path, mtime)
    return newest


# Stage-2 modules, in dependency order.
KALMAN_MODULES = [
    "kalman_concat",
    "kalman_filter",
    "kalman_assess",
    "kalman_offset",
]


def process_module(module_name, raw_dir, processed_dir, auto_yes=False, force=False):
    """
    Runs one processing module, with resume support: when the module's output
    already exists it is skipped (interactive mode asks; --yes mode skips
    automatically unless --force is given).
    Returns 'ok', 'skipped', or 'failed'.
    """
    try:
        module = importlib.import_module(f"processors.{module_name}")
    except ImportError as e:
        print(f"Error importing processors.{module_name}: {e}")
        sys.exit(1)

    out_path = module_output_path(module_name, processed_dir)
    newest_in = newest_existing_input(module_name, processed_dir)
    already_done = out_path is not None and out_path.exists()

    # Freshness check: an existing output that is OLDER than its input is
    # stale (the input was regenerated after this output was written).
    # Never skip a stale stage -- rerun it, in both interactive and --yes
    # modes, so a selective upstream rerun cannot ship mismatched outputs.
    stale = False
    if already_done and newest_in is not None:
        stale = out_path.stat().st_mtime < newest_in[1]

    if already_done and stale:
        print(f"\nWARNING: {module_name}: output {out_path.name} is OLDER than its "
              f"input {newest_in[0].name} -- the input was regenerated after this "
              f"output was written. Rerunning {module_name} instead of skipping "
              f"to avoid stale results.")
    elif already_done and not force:
        if auto_yes:
            print(f"\n[resume] {module_name}: output {out_path.name} already exists -- "
                  f"skipping (use --force to regenerate).")
            return "skipped"
        redo = input(f"{module_name}: output {out_path.name} already exists. "
                     f"Reprocess it? (yes/no): ").strip().lower()
        if redo != "yes":
            print(f"Skipping {module_name} (output kept).")
            return "skipped"
    elif not auto_yes and not already_done:
        proceed = input(f"Do you want to process {module_name}? (yes/no): ").strip().lower()
        if proceed != "yes":
            print(f"Skipping {module_name}.")
            return "skipped"

    # Add a special note for the UTM assessment module.
    if module_name == "kalman_offset":
        print(
            "\nNOTE: The offset Assessment step will offset the vehicle's location and save a final data file for upload in Unreal."
        )

    print(f"\nProcessing {module_name}...")
    try:
        rc = module.process_data(raw_dir, processed_dir)
    except Exception as e:
        print(f"\nERROR in {module_name}: {e}")
        import traceback
        traceback.print_exc()
        return "failed"
    # A module that RETURNS a truthy code has failed just as surely as one
    # that raised (some processors return 1 instead of raising). This value
    # used to be discarded, which made kalman_filter - the one module with
    # its own failure code - the one module whose failure could never reach
    # the orchestrator: it printed a traceback, returned 1, and this function
    # reported "done". Never convert it to 'ok'. (Fixed independently by
    # 0668a3e and fe2242c; this is the union.)
    if rc:
        print(f"\nERROR in {module_name}: process_data returned failure code "
              f"{rc!r}. Treating this stage as FAILED.")
        return "failed"
    print(f"Finished processing {module_name}.")
    return "ok"


def main():
    """
    Main script orchestrating the expedition data processing.
    """
    parser = argparse.ArgumentParser(description="ROV Kalman filter pipeline (stage 2)")
    parser.add_argument("--base", help="Base directory containing expeditions (e.g. Z:/)")
    parser.add_argument("--expedition", help="Expedition identifier (e.g. NA173)")
    parser.add_argument("--dive", help="Dive folder (e.g. H2075)")
    parser.add_argument("--yes", action="store_true",
                        help="Run all modules without per-module confirmation")
    parser.add_argument("--force", action="store_true",
                        help="Rerun modules even when their outputs already exist")
    args = parser.parse_args()

    print("--------------------------------------------------")
    print("     KALMAN FILTER DATA PROCESSING SCRIPT         ")
    print("--------------------------------------------------")

    raw_dir, processed_dir = get_directories(args)

    statuses = {}
    for module in KALMAN_MODULES:
        status = process_module(module, raw_dir, processed_dir,
                                auto_yes=args.yes, force=args.force)
        statuses[module] = status
        if status == "failed":
            print(f"\nAborting: {module} failed; downstream modules depend on its output.")
            break

    print("\n--------------------------------------------------")
    print("Run summary:")
    for name, status in statuses.items():
        marker = {"ok": "done", "skipped": "skipped", "failed": "FAILED"}[status]
        print(f"  {name:16s} {marker}")
    if any(s == "failed" for s in statuses.values()):
        print("Fix the issue and rerun -- completed modules will be skipped")
        print("automatically (use --force to redo them).")
        print("--------------------------------------------------")
        # Exit NON-ZERO on failure: this used to return 0 with modules marked
        # FAILED, so any caller gating on exit status treated a broken run as
        # a good one. Fixed independently on both sides -- 0668a3e returned a
        # code that __main__ sys.exit()s, fe2242c raised SystemExit(1) here.
        # Unified to the LOUDER contract: main() itself exits non-zero on
        # failure (even a caller that discards the return value cannot score
        # a broken run as good) and returns 0 on success for __main__'s
        # sys.exit(main()).
        sys.exit(1)
    print(f"Check '{processed_dir}' for output files.")
    print("--------------------------------------------------")
    return 0

if __name__ == "__main__":
    sys.exit(main())
