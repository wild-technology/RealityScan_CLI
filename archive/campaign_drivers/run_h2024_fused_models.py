"""Measure the FUSED H2024 components' metric scale and model the ones that
pass - the follow-up to run_h2024_final.py's phase 4.

Why this exists: the scale gate skipped every fused component as UNMEASURED,
including the hull. That is the gate working as designed - a merge-scene
`-exportXMPForSelectedComponent` writes ORDINAL sidecars (B10) that carry no
image identity, so the stem-pairing oracle cannot map members to solved
positions. Silence is not evidence, so it blocked.

The measurement here is correspondence-free and closes that blind spot for
fused components: under a similarity transform, SORTED distances-from-centroid
of the same camera set correspond rank-for-rank, so the ratio of matching
quantiles between the solved cloud (the ordinal pose sidecars in the fused
component's identity_r0) and the nav cloud (the manifest's member basenames
looked up in the union flight log) is the metric scale - median and IQR come
from the quantile-ratio distribution. It measures the DELIVERABLE, not its
inputs, which the EVALUATION_READY caveat has wanted since 2026-07-25.

Assumption stated: validity rests on the solve being a similarity transform of
the nav shape - which is precisely the hypothesis the scale gate exists to
test, and gross violations (a fold, drift) widen the quantile-ratio IQR and
are called out by the same wide-IQR rule the stem oracle uses.

No RealityScan probes; models only.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re
import sys
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import merge_zones  # noqa: E402
from modules import component_manifest, scale_oracle  # noqa: E402
from modules.realityscan_interface.realityscan_cli import RealityScanCLI  # noqa: E402

V2_ROOT = r"F:\na156_h2024_v2"
IMAGES_ROOT = os.path.join(V2_ROOT, "batched_images_by_zone")
PROJECT = os.path.join(V2_ROOT, "final_assembly", "assembly",
                       "H2024_Final_Assembly.rsproj")
UNION_LOG = os.path.join(V2_ROOT, "final_assembly",
                         "flight_log_scalegate_4Q_UTM.txt")
REPORT = os.path.join(V2_ROOT, "fused_models_report.json")
PROJECT_LABEL = "NA156_H2024_V2"

# Smallest first (cost ladder). Paths are the ORIGINAL export locations.
FUSED = [
    os.path.join(V2_ROOT, "nonhull", "cluster_4", "attempt_1_align_rematch",
                 "cluster_4_a1_c0.rsalign"),
    os.path.join(V2_ROOT, "nonhull", "cluster_1", "attempt_1_align_rematch",
                 "cluster_1_a1_c0.rsalign"),
    os.path.join(V2_ROOT, "merged5", "cluster_0", "attempt_2_align_rematch",
                 "cluster_0_a2_c0.rsalign"),
]

# The measurement now lives in modules/scale_oracle (promoted 2026-07-29 so
# the generic run_models.py driver and WildScan use ONE implementation);
# these thin wrappers keep this driver's numpy-array call shape.

def solved_positions(identity_dir: str) -> np.ndarray:
    return np.asarray(scale_oracle.solved_position_cloud(identity_dir),
                      dtype=np.float64)


def nav_positions(union_log: str, members: list[str]) -> np.ndarray:
    return np.asarray(
        scale_oracle.nav_position_multiset(union_log, members),
        dtype=np.float64)


COMPONENTS_ROOT = os.path.join(V2_ROOT, "aligned_components")


def member_multiset(manifest: dict) -> list[str]:
    return scale_oracle.member_multiset(manifest, COMPONENTS_ROOT)


def quantile_ratio_scale(solved: np.ndarray, nav: np.ndarray) -> dict | None:
    return scale_oracle.quantile_ratio_scale(
        [tuple(p) for p in solved], [tuple(p) for p in nav])


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(os.path.join(V2_ROOT, "fused_models.log"),
                                encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logger = logging.getLogger("fused_models")

    if not os.path.isfile(PROJECT):
        logger.error("assembly project missing: %s", PROJECT)
        return 1

    os.environ["RS_INSTANCE"] = "RS1"
    os.environ["RS_CACHE_DIR"] = r"E:\rscache"
    os.environ["RS_HEADLESS"] = "0"
    # Daily RC_projects copies are DEFERRED to the end (owner 2026-07-28:
    # "skip saves to save time until after the project is complete").
    # GenerateModel.bat takes two of them per component - one MID-RECIPE with
    # ~8 models live - and both are gated on RS_PROJECTS_DIR, so leaving it
    # unset skips them without touching the .bat. The per-component scene
    # save stays: the workflow loads, models and quits per component, so
    # without it that component's models would not persist at all.
    os.environ.pop("RS_PROJECTS_DIR", None)
    os.environ.pop("RS_PROJECT_LABEL", None)
    cli = RealityScanCLI(logging.getLogger("models"))
    logs_dir = os.path.join(V2_ROOT, "logs")

    report = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "components": []}

    def flush() -> None:
        with open(REPORT, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)

    for rsalign in FUSED:
        name = os.path.splitext(os.path.basename(rsalign))[0]
        manifest = component_manifest.load_manifest(rsalign + ".manifest.json")
        identity_dir = os.path.join(os.path.dirname(rsalign), "identity_r0")
        solved = solved_positions(identity_dir)
        nav = nav_positions(UNION_LOG, member_multiset(manifest))
        stats = quantile_ratio_scale(solved, nav)
        status, why = scale_oracle.verdict(stats)
        entry = {"component": name, "cameras": manifest.get("camera_count"),
                 "solved_points": int(len(solved)), "nav_points": int(len(nav)),
                 "scale": None if stats is None else stats["median"],
                 "status": status, "why": why,
                 "method": "quantile-ratio (correspondence-free, B10 ordinals)"}
        report["components"].append(entry)
        flush()
        logger.info("%s: %s - %s", name, status.upper(), why)
        if status != "pass":
            logger.error("SCALE GATE: %s not modelled (%s)", name, status)
            entry["skipped"] = "scale_gate"
            flush()
            continue

        import shutil
        free = shutil.disk_usage("F:\\").free / (1024 ** 3)
        if free < 50.0:
            logger.error("ABORT: F: at %.1f GB before %s", free, name)
            entry["skipped"] = "disk_floor"
            flush()
            break

        logger.info("=== model %s (%s cams) ===", name, entry["cameras"])
        started = time.time()
        res = cli.run_batch_script("GenerateModel.bat", [PROJECT, name],
                                   logs_dir)
        entry["success"] = res.success
        entry["errors"] = res.errors
        entry["duration_min"] = round((time.time() - started) / 60, 1)
        flush()
        logger.info("model %s: success=%s in %.1f min", name, res.success,
                    entry["duration_min"])
        if not res.success:
            logger.error("model %s FAILED - stopping so evidence survives",
                         name)
            break

    done = sum(1 for c in report["components"] if c.get("success"))

    # ONE dated copy, now that the project is complete - the deferred save.
    modelled = [c for c in report["components"] if c.get("success")]
    if modelled:
        logger.info("=== project complete: taking the single dated copy ===")
        merge_zones.set_project_save_env(IMAGES_ROOT, PROJECT_LABEL)
        dated = os.path.join(
            os.environ["RS_PROJECTS_DIR"],
            f'{PROJECT_LABEL}_merged_{os.environ["RS_PROJECT_DATE"]}.rsproj')
        started = time.time()
        res = cli.run_batch_script("SaveProjectCopy.bat", [PROJECT, dated],
                                   logs_dir)
        report["dated_copy"] = {"path": dated, "success": res.success,
                                "duration_min": round((time.time() - started) / 60, 1)}
        flush()
        logger.info("dated copy: success=%s in %.1f min -> %s", res.success,
                    report["dated_copy"]["duration_min"], dated)

    logger.info("DONE: %d fused model(s) completed. Report: %s", done, REPORT)
    return 0 if done else 1


if __name__ == "__main__":
    raise SystemExit(main())
