"""H2024 final chain (owner staging 2026-07-28): non-hull merge -> hull
assembly -> confirmation -> per-component models.

Phase 1  merge the eight non-hull components under the NEW logic:
         pair_gate=overlap (unique = no shared imagery AND no true bbox
         overlap), mechanism-aware rungs (merge only when the shared-image
         graph spans the subset), bounded loss 0.25%.
Phase 2  assemble_only: the non-hull finals + the hull
         (merged5/cluster_0/attempt_2_align_rematch/cluster_0_a2_c0.rsalign,
         imported from its original export location, hard rule 7) into ONE
         georeferenced project. Owner nominal: 7 components total.
Phase 3  confirm - component count vs nominal, per-component scale verdicts
         from the phase-2 report, rslog import validation.
Phase 4  models per component, smallest first (cost ladder: the pipeline is
         proven on a cheap component before the hull spends hours). Scale
         gate enforced from the phase-2 verdicts.

Resumable: each phase is skipped when its terminal artifact already exists.
No RealityScan probes run here - probes are queued until modeling completes
(owner instruction).
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import merge_zones  # noqa: E402
from modules.realityscan_interface.realityscan_cli import RealityScanCLI  # noqa: E402

V2_ROOT = r"F:\na156_h2024_v2"
IMAGES_ROOT = os.path.join(V2_ROOT, "batched_images_by_zone")
COMPONENTS_ROOT = os.path.join(V2_ROOT, "aligned_components")
NONHULL_OUT = os.path.join(V2_ROOT, "nonhull")
FINAL_OUT = os.path.join(V2_ROOT, "final_assembly")
REPORT = os.path.join(V2_ROOT, "final_report.json")
PROJECT_LABEL = "NA156_H2024_V2"
NOMINAL_COMPONENTS = 7

HULL = os.path.join(V2_ROOT, "merged5", "cluster_0", "attempt_2_align_rematch",
                    "cluster_0_a2_c0.rsalign")
NONHULL = [
    os.path.join(COMPONENTS_ROOT, "zone_1", f"zone_1_c{i}.rsalign")
    for i in (0, 1, 2, 4, 5)
] + [
    os.path.join(COMPONENTS_ROOT, "zone_4", f"zone_4_c{i}.rsalign")
    for i in (0, 1, 2)
]

MIN_FREE_GB = 50.0


def free_gb(drive: str) -> float:
    import shutil
    return shutil.disk_usage(drive).free / (1024 ** 3)


def check_space(logger: logging.Logger, stage: str) -> bool:
    e, f = free_gb("E:\\"), free_gb("F:\\")
    logger.info("%s: free space E: %.1f GB (cache), F: %.1f GB (project)",
                stage, e, f)
    if f < MIN_FREE_GB or e < MIN_FREE_GB:
        logger.error("ABORT before %s: below the %.0f GB floor", stage,
                     MIN_FREE_GB)
        return False
    return True


def write_complist(path: str, entries: list[str]) -> None:
    """BOM-free, CRLF - PS 5.1's Set-Content -Encoding utf8 writes a BOM that
    silently invalidates the first entry (FINDINGS 2026-07-27)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write("\n".join(entries) + "\n")


def run_merge_zones(args: list[str], log_name: str,
                    logger: logging.Logger) -> int:
    env = dict(os.environ)
    env["RS_INSTANCE"] = "RS1"          # a real input since the 07-28 fix
    env["RS_CACHE_DIR"] = r"E:\rscache"
    env["RS_HEADLESS"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    cmd = [sys.executable, os.path.join(REPO, "merge_zones.py")] + args
    started = time.time()
    proc = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True,
                          text=True, stdin=subprocess.DEVNULL)
    log_path = os.path.join(V2_ROOT, "logs", log_name)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as fh:
        fh.write(proc.stdout or "")
        fh.write("\n--- STDERR ---\n")
        fh.write(proc.stderr or "")
    logger.info("merge_zones exited %d after %.1f min (log %s)",
                proc.returncode, (time.time() - started) / 60, log_path)
    if proc.returncode != 0:
        logger.error("STDERR tail:\n%s", (proc.stderr or "")[-3000:])
    return proc.returncode


def _terminal_report(report_path: str) -> dict | None:
    """The report ONLY counts as a phase's terminal artifact when it carries
    the assembly section - merge_zones flushes after every cluster, so a
    mid-run abort (including the instrument invariant, which raises by
    design) leaves a valid-looking PARTIAL file. Skipping on existence made
    a rerun assemble and model an assembly silently missing whole clusters
    (final review)."""
    if not os.path.isfile(report_path):
        return None
    with open(report_path, encoding="utf-8") as fh:
        report = json.load(fh)
    if "assembly" not in report:
        logging.getLogger("h2024_final").warning(
            "%s exists but is PARTIAL (no assembly section) - rerunning the "
            "phase", report_path)
        return None
    return report


def phase1_nonhull(logger: logging.Logger) -> dict | None:
    report_path = os.path.join(NONHULL_OUT, "merge_report.json")
    report = _terminal_report(report_path)
    if report is not None:
        logger.info("phase 1: terminal report already exists - skipping")
        return report
    complist = os.path.join(NONHULL_OUT, "nonhull.complist")
    write_complist(complist, NONHULL)
    rc = run_merge_zones([
        "--components_root", COMPONENTS_ROOT,
        "--complist", complist,
        "--images_root", IMAGES_ROOT,
        "--output", NONHULL_OUT,
        "--name", "H2024_NonHull",
        "--min_size", "50", "--target", "0.95",
        "--project_label", PROJECT_LABEL,
        "--visible", "true", "--auto_model", "false",
        "--ladder", "merge_first", "--merge_scope", "neighbour",
        "--pair_gate", "overlap", "--assemble_only", "false",
        "--loss_tolerance", "0.0025", "--scale_gate", "true",
        "--scale_min", "0.9", "--scale_max", "1.1",
    ], "phase1_nonhull.log", logger)
    if rc != 0:
        return None
    with open(report_path, encoding="utf-8") as fh:
        return json.load(fh)


def phase2_assembly(nonhull_report: dict, logger: logging.Logger) -> dict | None:
    report_path = os.path.join(FINAL_OUT, "merge_report.json")
    report = _terminal_report(report_path)
    if report is not None:
        logger.info("phase 2: terminal report already exists - skipping")
        return report
    finals = [c["rsalign"]
              for rec in nonhull_report.get("clusters", [])
              for c in rec.get("final_components", [])]
    if not finals:
        logger.error("phase 2: no final components in the non-hull report")
        return None
    if not os.path.isfile(HULL):
        logger.error("phase 2: hull export missing: %s", HULL)
        return None
    complist = os.path.join(FINAL_OUT, "final.complist")
    # Hull last - imported into the completed non-hull scene (owner staging).
    write_complist(complist, finals + [HULL])
    logger.info("phase 2: %d non-hull final(s) + hull", len(finals))
    rc = run_merge_zones([
        "--components_root", COMPONENTS_ROOT,
        "--complist", complist,
        "--images_root", IMAGES_ROOT,
        "--output", FINAL_OUT,
        "--name", "H2024_Final_Assembly",
        "--min_size", "50", "--target", "0.95",
        "--project_label", PROJECT_LABEL,
        "--visible", "true", "--auto_model", "false",
        "--ladder", "merge_first", "--merge_scope", "neighbour",
        "--pair_gate", "overlap", "--assemble_only", "true",
        "--loss_tolerance", "0.0025", "--scale_gate", "true",
        "--scale_min", "0.9", "--scale_max", "1.1",
    ], "phase2_assembly.log", logger)
    if rc != 0:
        return None
    with open(report_path, encoding="utf-8") as fh:
        return json.load(fh)


def phase3_confirm(final_report: dict, logger: logging.Logger) -> dict:
    finals = [c for rec in final_report.get("clusters", [])
              for c in rec.get("final_components", [])]
    scales = final_report.get("input_scales", {})
    verdicts = {}
    for c in finals:
        v = scales.get(c["key"], {})
        verdicts[c["key"]] = {
            "cameras": c.get("camera_count"),
            "scale_status": v.get("status", "unmeasured"),
            "scale": v.get("median"),
        }
        logger.info("  %-28s %5s cams  scale %s (%s)", c["key"],
                    c.get("camera_count"), v.get("median"),
                    v.get("status", "unmeasured"))
    count = len(finals)
    confirmation = {
        "component_count": count,
        "nominal": NOMINAL_COMPONENTS,
        "matches_nominal": count == NOMINAL_COMPONENTS,
        "all_scales_pass": all(v["scale_status"] == "pass"
                               for v in verdicts.values()),
        "verdicts": verdicts,
        "project": final_report.get("assembly", {}).get("project"),
    }
    if count != NOMINAL_COMPONENTS:
        logger.warning("component count %d differs from nominal %d - "
                       "recorded as divergence, proceeding on soundness "
                       "(every component scale-checked)", count,
                       NOMINAL_COMPONENTS)
    if not confirmation["all_scales_pass"]:
        logger.error("not every component passes the scale band - models for "
                     "failing components will be BLOCKED")
    return confirmation


def phase4_models(confirmation: dict, logger: logging.Logger) -> list[dict]:
    project = confirmation.get("project")
    if not project or not os.path.isfile(project):
        logger.error("phase 4: assembly project missing: %s", project)
        return []
    os.environ["RS_INSTANCE"] = "RS1"
    os.environ["RS_CACHE_DIR"] = r"E:\rscache"
    os.environ["RS_HEADLESS"] = "0"
    # Dated RC_projects copies stay DEFERRED (owner 2026-07-28): arming
    # RS_PROJECTS_DIR here made GenerateModel.bat take two per-component
    # copies, one mid-recipe with ~15 models live (final review).
    os.environ.pop("RS_PROJECTS_DIR", None)
    os.environ.pop("RS_PROJECT_LABEL", None)
    cli = RealityScanCLI(logging.getLogger("models"))
    logs_dir = os.path.join(V2_ROOT, "logs")

    # Smallest first: the model recipe is proven on a cheap component before
    # the hull commits hours (cost-ladder discipline).
    order = sorted(confirmation["verdicts"].items(),
                   key=lambda kv: kv[1]["cameras"] or 0)
    results = []
    for key, verdict in order:
        comp_name = key.split("/", 1)[-1]
        if verdict["scale_status"] != "pass":
            logger.error("SCALE GATE: skipping model for %s (%s)", comp_name,
                         verdict["scale_status"])
            results.append({"component": comp_name, "skipped": "scale_gate"})
            continue
        if not check_space(logger, f"model:{comp_name}"):
            results.append({"component": comp_name, "skipped": "disk_floor"})
            break
        logger.info("=== model %s (%s cams) ===", comp_name, verdict["cameras"])
        started = time.time()
        res = cli.run_batch_script("GenerateModel.bat", [project, comp_name],
                                   logs_dir)
        entry = {"component": comp_name, "cameras": verdict["cameras"],
                 "success": res.success, "errors": res.errors,
                 "duration_min": round((time.time() - started) / 60, 1)}
        results.append(entry)
        logger.info("model %s: success=%s in %.1f min", comp_name,
                    res.success, entry["duration_min"])
        if not res.success:
            logger.error("model %s FAILED - stopping the chain so the "
                         "evidence is not overwritten", comp_name)
            break
    return results


def main() -> int:
    os.makedirs(os.path.join(V2_ROOT, "logs"), exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(os.path.join(V2_ROOT, "final_driver.log"),
                                encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logger = logging.getLogger("h2024_final")
    report: dict = {"started": time.strftime("%Y-%m-%d %H:%M:%S")}

    def flush() -> None:
        with open(REPORT, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)

    # The reparse guard lives in run_h2024_v2 - a junctioned image tree
    # silently blinds both the XMP export and the peel harvest.
    from run_h2024_v2 import assert_harvestable  # noqa: E402
    assert_harvestable(IMAGES_ROOT, logger)

    if not check_space(logger, "phase 1"):
        return 1
    nonhull = phase1_nonhull(logger)
    report["phase1_done"] = nonhull is not None
    flush()
    if nonhull is None:
        return 1

    if not check_space(logger, "phase 2"):
        return 1
    final = phase2_assembly(nonhull, logger)
    report["phase2_done"] = final is not None
    flush()
    if final is None:
        return 1

    confirmation = phase3_confirm(final, logger)
    report["confirmation"] = confirmation
    flush()

    report["models"] = phase4_models(confirmation, logger)
    flush()

    done = [m for m in report["models"] if m.get("success")]
    logger.info("DONE: %d model(s) completed. Report: %s", len(done), REPORT)
    return 0 if done and all(m.get("success") or m.get("skipped")
                             for m in report["models"]) else 1


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    raise SystemExit(main())
