r"""Unattended ON2026 wreck driver: per-zone aligns, then cross-zone merge
with auto-model (mesh+texture per surviving component).

Modeled on run_h2024_v2.py. Differences, deliberate:
- Priors come from COLMAP (sparse/0, 99.2%% registered, 0.706 px true
  median), not USBL nav: 0.02 m position / 90 deg orientation accuracies
  in a LOCAL Euclidean frame (FlightLogParams template swapped to local:1
  for this campaign; validated FINDINGS C-20260730-05).
- Alignment params: ON2026_AlignmentParams.xml via RS_ALIGN_PARAMS
  (Brown3 + High sensitivity for rectified VOYIS pairs; the NA167
  template keeps Division/Ultra for its own rig).
- No calibration sidecars: the camera registry has no VOYIS families and
  the fixture probe registered 20/20 without them.
- merge: --loss_tolerance 0.005 passed EXPLICITLY for the unattended run
  (owner normally decides this; 0 = exact-only rejected every solver-lossy
  fusion on H2024). Revisit in the morning gate.

Resumable: zones with existing manifests are skipped; the merge stage is
skipped if merged\ already holds an assembly report.

Driver log: M:\ON2026 COLMAP processing\rs\driver_rs.log (same ===/ABORT/
DONE line format the session monitors expect).
"""
from __future__ import annotations

import datetime
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = r"M:\ON2026 COLMAP processing\rs"
IMAGES_ROOT = os.path.join(ROOT, "batched_images_by_zone")
COMPONENTS_ROOT = os.path.join(ROOT, "aligned_components")
MERGE_DIR = os.path.join(ROOT, "merged")
LOGS = os.path.join(ROOT, "logs")
DRIVER_LOG = os.path.join(ROOT, "driver_rs.log")
MIN_FREE_GB = 150.0

ENV = dict(os.environ)
ENV.update({
    "RS_MODULES": "RealityScan Alignment",
    "RS_NO_INTERACTIVE": "1",
    "RS_INSTANCE": "RS1",
    "RS_CACHE_DIR": r"M:\rs_cache",
    "RS_ALIGN_PARAMS": os.path.join(ROOT, "ON2026_AlignmentParams.xml"),
    "PYTHONIOENCODING": "utf-8",
})


def log(msg):
    line = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} | {msg}"
    print(line, flush=True)
    with open(DRIVER_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def free_gb(path):
    return shutil.disk_usage(path).free / 1e9


def zone_done(zone):
    zdir = os.path.join(COMPONENTS_ROOT, zone)
    if not os.path.isdir(zdir):
        return False
    names = os.listdir(zdir)
    return any(n.endswith(".rsalign") for n in names) and any(
        n.endswith(".json") for n in names)


def run_stage(name, cmd, log_file):
    log(f"=== {name} starting")
    t0 = time.time()
    with open(log_file, "w", encoding="utf-8") as fh:
        proc = subprocess.run(cmd, cwd=REPO, env=ENV, stdout=fh,
                              stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL)
    mins = (time.time() - t0) / 60
    if proc.returncode != 0:
        log(f"ABORT: {name} failed rc={proc.returncode} after {mins:.1f} min - see {log_file}")
        sys.exit(1)
    log(f"=== {name} finished rc=0 after {mins:.1f} min")


def main():
    os.makedirs(LOGS, exist_ok=True)
    zones = sorted(
        (z for z in os.listdir(IMAGES_ROOT)
         if os.path.isdir(os.path.join(IMAGES_ROOT, z)) and z.startswith("zone_")),
        key=lambda z: int(z.split("_")[1]))
    if not zones:
        log("ABORT: no zones found under " + IMAGES_ROOT)
        sys.exit(1)
    log(f"driver start: {len(zones)} zones, instance RS1, cache M:\\rs_cache")

    for zone in zones:
        if zone_done(zone):
            log(f"=== {zone} SKIPPED (components already exported)")
            continue
        if free_gb(ROOT) < MIN_FREE_GB:
            log(f"ABORT: M: free space below {MIN_FREE_GB} GB")
            sys.exit(1)
        zdir = os.path.join(IMAGES_ROOT, zone)
        zlog = os.path.join(zdir, "flight_log_UTM.txt")
        if not os.path.isfile(zlog):
            log(f"ABORT: missing flight log for {zone}: {zlog}")
            sys.exit(1)
        run_stage(f"align {zone}", [
            sys.executable, os.path.join(REPO, "main.py"),
            "--output_dir", ROOT,
            "--continue_automatically", "true",
            "--r_input", zdir,
            "--r_flight_log", zlog,
            "--r_project_label", "",
            "--r_model_generate", "false",
            "--r_model_cull_poly", "false",
            "--r_model_texture", "false",
            "--r_model_simplify", "false",
            "--r_display_output", "false",
        ], os.path.join(LOGS, f"{zone}_align.log"))

    # MERGE PATH RETIRED 2026-08-02: RS merge scenes unifying everything
    # hold ~44k cameras (fused core + remaining zones + duplicate overlap
    # copies) and exceed this 192 GB box - attempt 2 died inside RS with
    # 0x8007000E at 319.5 GB commit; attempt 3 OOM'd the driver Python.
    # The merge DID prove the geometry (attempt 1: 10 zones fused into
    # cluster_0_a1_c0 = 29,302 cams, 361 lost, accepted; preserved under
    # rs\merged...). Final unification instead comes from a MONOLITH align
    # of all 38,948 unique images (no merge scene, no duplicate cameras)
    # with the zone-validated recipe: Division + georef-merge + High +
    # 0.02 m / 90 deg priors in local:1 (RS_ALIGN_PARAMS + the local
    # FlightLogParams template). Fallback if this OOMs: GenerateModel on
    # the fused 29,302-cam core.
    # All RealityScan execution goes through RealityScanCLI (hard rule 1:
    # never add a second launch path) - it owns marker hygiene, locking,
    # progress tailing, stall warnings and verified shutdown.
    import logging
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    from modules.realityscan_interface.realityscan_cli import RealityScanCLI
    os.environ.update(ENV)
    cli = RealityScanCLI(logging.getLogger("on2026"))

    def run_rs_stage(name, script, args):
        log(f"=== {name} starting")
        t0 = time.time()
        result = cli.run_batch_script(script, args, LOGS)
        mins = (time.time() - t0) / 60
        if not result.success:
            log(f"ABORT: {name} failed after {mins:.1f} min - "
                f"{result.errors or result.return_code} (log: {result.log_path})")
            sys.exit(1)
        log(f"=== {name} finished rc=0 after {mins:.1f} min")

    metadata = os.path.join(REPO, "modules", "realityscan_interface", "RS_CLI", "Metadata")
    mono_dir = os.path.join(ROOT, "monolith")
    scene = os.path.join(mono_dir, "on2026_wreck.rsproj")
    if not os.path.isfile(scene):
        run_rs_stage("monolith align (38,948 images)", "AlignZone.bat", [
            os.path.join(ROOT, "rs_images"),
            mono_dir,
            os.path.join(ROOT, "flight_log_zones.txt"),
            os.path.join(metadata, "FlightLogParams.xml"),
            "on2026_wreck", "100",
        ])
    else:
        log("=== monolith align SKIPPED (scene exists)")
    run_rs_stage("model+texture (maximal component)", "GenerateModel.bat",
                 [scene, ""])

    log("driver DONE")


if __name__ == "__main__":
    main()
