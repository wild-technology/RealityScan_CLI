"""Unattended H2024 v2 driver: fresh per-zone aligns, then the cross-zone merge.

Runs the five H2024 zones sequentially through the RealityScan Alignment
module, compares the resulting components against the 2026-07-26 baseline
(the regression check the owner asked for), then runs merge_zones.py to
produce ONE assembly project.

Workspace layout, deliberate:
  F:/na156_h2024            baseline - READ ONLY here, never written
  F:/na156_h2024_v2         this run; batched_images_by_zone holds per-zone
                            REAL directories of hardlinks back to the shared
                            image tree (sidecars/flight logs are copies).
                            NEVER junctions - see assert_harvestable below
                            and the IMAGES_ROOT comment.

GUI-visible by owner instruction (RS_HEADLESS=0). Cache pinned to E: - the
2026-07-26 hull failures were ERROR_DISK_FULL on the CACHE drive, which
otherwise follows the drive of the path it is given.

Resumable: a zone whose components already exist in v2 is skipped unless
--force. Stage results are flushed to run_report.json after every zone.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from modules import camera_registry  # noqa: E402

V2_ROOT = r"F:\na156_h2024_v2"
# The one image tree every stage uses. It holds per-zone directories of
# HARDLINKS back to F:/na156_h2024/batched_images_by_zone (sidecars and flight
# logs are COPIES, so a write here cannot corrupt the baseline's). It was
# briefly per-zone JUNCTIONS, which silently broke the merge in both
# directions - RealityScan writes no XMP sidecars behind a reparse point, and
# `Get-ChildItem -Recurse` skips reparse-point children - costing two full
# merge runs (FINDINGS 2026-07-27/28). assert_harvestable() below refuses to
# start if anyone re-junctions it.
IMAGES_ROOT = os.path.join(V2_ROOT, "batched_images_by_zone")
COMPONENTS_ROOT = os.path.join(V2_ROOT, "aligned_components")
BASELINE = os.path.join(V2_ROOT, "BASELINE_20260726.json")
REPORT = os.path.join(V2_ROOT, "run_report.json")
PROJECT_LABEL = "NA156_H2024_V2"
ZONES = ["zone_1", "zone_2", "zone_3", "zone_4", "zone_5"]

# Abort thresholds. Free space is the resource that actually killed a run
# here; RAM is watched but has never been the binding constraint.
MIN_FREE_GB_CACHE = 50.0
MIN_FREE_GB_PROJECT = 50.0


def free_gb(path: str) -> float:
    import shutil
    return shutil.disk_usage(path).free / (1024 ** 3)


def check_space(logger: logging.Logger) -> bool:
    cache = free_gb("E:\\")
    project = free_gb("F:\\")
    logger.info("free space: E: %.1f GB (cache), F: %.1f GB (project)", cache, project)
    if cache < MIN_FREE_GB_CACHE:
        logger.error("ABORT: cache drive E: below %.0f GB", MIN_FREE_GB_CACHE)
        return False
    if project < MIN_FREE_GB_PROJECT:
        logger.error("ABORT: project drive F: below %.0f GB", MIN_FREE_GB_PROJECT)
        return False
    return True


def zone_already_done(zone: str) -> bool:
    zone_dir = os.path.join(COMPONENTS_ROOT, zone)
    if not os.path.isdir(zone_dir):
        return False
    return any(f.endswith(".rsalign") for f in os.listdir(zone_dir))


def align_zone(zone: str, logger: logging.Logger) -> dict:
    """Run one zone through the alignment module as a single scene."""
    zone_images = os.path.join(IMAGES_ROOT, zone)
    flight_log = os.path.join(zone_images, "flight_log_4Q_UTM.txt")
    if not os.path.isfile(flight_log):
        raise FileNotFoundError(f"no flight log for {zone}: {flight_log}")

    created, unknown = camera_registry.ensure_calibration_sidecars(zone_images)
    logger.info("%s: calibration sidecars restored=%d unknown_camera=%d",
                zone, created, unknown)

    env = dict(os.environ)
    env["RS_MODULES"] = "RealityScan Alignment"
    env["RS_NO_INTERACTIVE"] = "1"
    env["RS_HEADLESS"] = "0"
    env["RS_INSTANCE"] = "RS1"
    env["RS_CACHE_DIR"] = r"E:\rscache"
    env["PYTHONIOENCODING"] = "utf-8"

    cmd = [
        sys.executable, os.path.join(REPO, "main.py"),
        "--output_dir", V2_ROOT,
        "--r_input", zone_images,
        "--r_flight_log", flight_log,
        "--r_project_label", PROJECT_LABEL,
        "--r_model_generate", "false",
        "--r_model_cull_poly", "false",
        "--r_model_texture", "false",
        "--r_model_simplify", "false",
        "--r_display_output", "false",
    ]
    logger.info("%s: launching alignment", zone)
    started = time.time()
    proc = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True,
                          text=True, stdin=subprocess.DEVNULL)
    duration = time.time() - started

    tail = (proc.stdout or "")[-4000:]
    err_tail = (proc.stderr or "")[-4000:]
    log_path = os.path.join(V2_ROOT, "logs", f"{zone}_align.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as fh:
        fh.write(proc.stdout or "")
        fh.write("\n--- STDERR ---\n")
        fh.write(proc.stderr or "")

    result = {
        "zone": zone,
        "returncode": proc.returncode,
        "duration_s": round(duration, 1),
        "log": log_path,
        "components": census_zone(zone),
    }
    if proc.returncode != 0:
        logger.error("%s: alignment exited %d after %.1f min\nSTDOUT tail:\n%s\n"
                     "STDERR tail:\n%s", zone, proc.returncode, duration / 60,
                     tail, err_tail)
    else:
        logger.info("%s: alignment finished in %.1f min -> %d component(s), %d cameras",
                    zone, duration / 60, result["components"]["component_count"],
                    result["components"]["cameras"])
    return result


def census_zone(zone: str) -> dict:
    """Read the manifests this zone's align produced."""
    zone_dir = os.path.join(COMPONENTS_ROOT, zone)
    components = []
    if os.path.isdir(zone_dir):
        for name in sorted(os.listdir(zone_dir)):
            if not name.endswith(".json"):
                continue
            with open(os.path.join(zone_dir, name), encoding="utf-8") as fh:
                manifest = json.load(fh)
            components.append({
                "component": manifest.get("component"),
                "camera_count": manifest.get("camera_count"),
                "members": len(manifest.get("images") or []),
            })
    return {
        "component_count": len(components),
        "cameras": sum(c["camera_count"] or 0 for c in components),
        "components": components,
    }


def compare_to_baseline(report: dict, logger: logging.Logger) -> dict:
    """The regression check: did the v2 aligns degrade any zone?"""
    with open(BASELINE, encoding="utf-8") as fh:
        baseline = json.load(fh)

    rows, degraded = [], []
    for zone in ZONES:
        base = baseline["zones"].get(zone, {})
        new = report["zones"].get(zone, {}).get("components", {})
        base_cams = base.get("cameras", 0)
        new_cams = new.get("cameras", 0)
        base_comps = base.get("component_count", 0)
        new_comps = new.get("component_count", 0)
        delta = new_cams - base_cams
        row = {
            "zone": zone,
            "baseline_components": base_comps, "v2_components": new_comps,
            "baseline_cameras": base_cams, "v2_cameras": new_cams,
            "camera_delta": delta,
            "pct": round(100.0 * delta / base_cams, 2) if base_cams else None,
        }
        # Degradation is a camera LOSS. A component-count change alone is not
        # degradation - fragmentation is a known nondeterministic behaviour and
        # fewer components is usually better.
        if delta < 0:
            degraded.append(row)
        rows.append(row)
        logger.info("%-8s baseline %d comps/%d cams -> v2 %d comps/%d cams  delta %+d",
                    zone, base_comps, base_cams, new_comps, new_cams, delta)

    verdict = "NO DEGRADATION" if not degraded else "DEGRADED"
    logger.info("REGRESSION VERDICT: %s", verdict)
    if degraded:
        for row in degraded:
            logger.error("  %s lost %d cameras (%.2f%%)", row["zone"],
                         -row["camera_delta"], row["pct"])
    return {"verdict": verdict, "rows": rows, "degraded": degraded}


def assert_harvestable(images_root: str, logger: logging.Logger) -> None:
    """The peel harvest is a PowerShell `Get-ChildItem -Recurse`, which does
    NOT descend into junction CHILDREN at ANY depth. Handing merge_zones.py a
    directory containing reparse points yields an empty peel on every attempt,
    which the driver cannot distinguish from a legitimately empty scene - it
    silently discarded a real 3-way fusion on 2026-07-27 (FINDINGS). The scan
    is recursive: a junction one level down (zone_1/cinema as a link)
    reproduces the blindness just as completely as a top-level one
    (final review).
    """
    def is_reparse(path: str) -> bool:
        if os.path.islink(path):
            return True
        # islink() is False for Windows junctions on some Python builds;
        # the reparse attribute is the reliable test.
        try:
            return bool(os.stat(path, follow_symlinks=False).st_reparse_tag)
        except (AttributeError, OSError):
            return False

    reparse = []
    for dirpath, dirnames, _files in os.walk(images_root):
        for name in list(dirnames):
            full = os.path.join(dirpath, name)
            if is_reparse(full):
                reparse.append(os.path.relpath(full, images_root))
                dirnames.remove(name)   # do not descend into the link
    if reparse:
        raise RuntimeError(
            f"images_root {images_root} has reparse-point children {reparse}; "
            "the peel harvest cannot cross them. Pass the real image tree.")
    logger.info("images_root %s is harvestable (no reparse-point children)",
                images_root)


def run_merge(logger: logging.Logger) -> dict:
    """Cross-zone merge over the v2 components, into one assembly project.

    Walks the V2 image tree, because that is the path baked into every v2
    .rsalign and therefore the only place RealityScan will write the pose
    sidecars the peel harvest reads. That tree used to be per-zone junctions,
    which silently defeated BOTH the write (RealityScan writes nothing behind
    a reparse point) and the read (`Get-ChildItem -Recurse` skips reparse-point
    children). It is now real directories of hardlinks, so `assert_harvestable`
    passes - and if anyone re-junctions it, the guard stops the run instead of
    burning hours on an empty instrument.
    """
    images_root = IMAGES_ROOT
    assert_harvestable(images_root, logger)
    output = os.path.join(V2_ROOT, "merged5")
    env = dict(os.environ)
    env["RS_HEADLESS"] = "0"
    env["RS_INSTANCE"] = "RS1"
    env["RS_CACHE_DIR"] = r"E:\rscache"
    env["PYTHONIOENCODING"] = "utf-8"

    cmd = [
        sys.executable, os.path.join(REPO, "merge_zones.py"),
        "--components_root", COMPONENTS_ROOT,
        "--images_root", IMAGES_ROOT,
        "--output", output,
        "--name", "H2024_V2_Assembly",
        "--min_size", "50",
        "--target", "0.95",
        "--project_label", PROJECT_LABEL,
        "--visible", "true",
        "--auto_model", "false",
        "--ladder", "merge_first",
        "--merge_scope", "neighbour",
        "--scale_gate", "true",
        # Owner decision 2026-07-28. The hull fuses 4,860 of 4,865 cameras on
        # every rung; exact-subset-sum attribution cannot see a fusion that
        # dropped 5, so it was rejected three times. 0.25% is ~12 cameras on
        # cluster_0 and every accepted loss is recorded per attempt and in
        # EVALUATION_READY.
        "--loss_tolerance", "0.0025",
        # EVERY ask()-backed option is pinned. An unpinned option makes
        # merge_zones prompt: on an inherited console the prompt goes into the
        # captured pipe and input() blocks forever; detached, the value is
        # silently inherited from whatever session last wrote rs_settings.json
        # (final review) - either way not this driver's configuration.
        "--pair_gate", "overlap",
        "--assemble_only", "false",
        "--scale_min", "0.9",
        "--scale_max", "1.1",
    ]
    logger.info("launching cross-zone merge -> %s", output)
    started = time.time()
    proc = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True,
                          text=True, stdin=subprocess.DEVNULL)
    duration = time.time() - started

    log_path = os.path.join(V2_ROOT, "logs", "merge.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as fh:
        fh.write(proc.stdout or "")
        fh.write("\n--- STDERR ---\n")
        fh.write(proc.stderr or "")

    logger.info("merge exited %d after %.1f min", proc.returncode, duration / 60)
    if proc.returncode != 0:
        logger.error("merge STDERR tail:\n%s", (proc.stderr or "")[-4000:])
    return {"returncode": proc.returncode, "duration_s": round(duration, 1),
            "output": output, "log": log_path}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true",
                        help="re-align zones that already have components in v2")
    parser.add_argument("--skip_merge", action="store_true",
                        help="run the aligns and the regression check only")
    args = parser.parse_args()

    os.makedirs(os.path.join(V2_ROOT, "logs"), exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(os.path.join(V2_ROOT, "driver.log"), encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logger = logging.getLogger("h2024_v2")

    report: dict = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "zones": {}}

    def flush() -> None:
        with open(REPORT, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)

    logger.info("=" * 72)
    logger.info("H2024 v2: fresh per-zone aligns + cross-zone merge, GUI visible")
    logger.info("=" * 72)

    for zone in ZONES:
        if not check_space(logger):
            report["aborted"] = f"insufficient disk before {zone}"
            flush()
            return 1
        if zone_already_done(zone) and not args.force:
            logger.info("%s: components already present in v2 - skipping "
                        "(use --force to re-run)", zone)
            report["zones"][zone] = {"skipped": True, "components": census_zone(zone)}
            flush()
            continue
        report["zones"][zone] = align_zone(zone, logger)
        flush()

    failed = [z for z, r in report["zones"].items()
              if not r.get("skipped") and r.get("returncode") not in (0, None)]
    if failed:
        logger.error("zones failed: %s - stopping before the merge", failed)
        report["aborted"] = f"zone alignment failed: {failed}"
        flush()
        return 1

    report["regression"] = compare_to_baseline(report, logger)
    flush()

    if args.skip_merge:
        logger.info("--skip_merge set: stopping after the regression check")
        return 0

    report["merge"] = run_merge(logger)
    flush()

    logger.info("DONE. report: %s", REPORT)
    return 0 if report["merge"]["returncode"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
