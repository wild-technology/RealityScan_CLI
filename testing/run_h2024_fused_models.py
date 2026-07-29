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

# RealityScan writes Position as an ELEMENT (<xcr:Position>x y z</...>) in
# current exports and as an attribute in some older ones - accept both.
_POS_ELEM = re.compile(r'<xcr:Position>([^<]+)</xcr:Position>')
_POS_ATTR = re.compile(r'xcr:Position="([^"]+)"')


def solved_positions(identity_dir: str) -> np.ndarray:
    """Solved camera positions from the pose sidecars. The frame is the model
    frame, not UTM - irrelevant here, because distance RATIOS are invariant
    under rigid motion and the scale factor is exactly what is measured."""
    pts = []
    for path in glob.glob(os.path.join(identity_dir, "*.xmp")):
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        m = _POS_ELEM.search(text) or _POS_ATTR.search(text)
        if m:
            vals = [float(v) for v in m.group(1).split()]
            if len(vals) == 3:
                pts.append(vals)
    return np.asarray(pts, dtype=np.float64)


def nav_positions(union_log: str, members: list[str]) -> np.ndarray:
    """Nav position per MEMBER OCCURRENCE, not per unique basename: the
    batcher copies overlap images into two zones, so a fused component holds
    TWO cameras for one basename - both really at that nav point. Collapsing
    them (the first version of this function) under-represented the nav cloud
    by 13% on the hull and tripped the cardinality guard."""
    table: dict[str, list[float]] = {}
    with open(union_log, encoding="utf-8") as fh:
        fh.readline()
        for line in fh:
            parts = line.split(";")
            if len(parts) >= 4:
                table[parts[0].strip().lower()] = [
                    float(parts[1]), float(parts[2]), float(parts[3])]
    pts = [table[m.lower()] for m in members if m.lower() in table]
    return np.asarray(pts, dtype=np.float64)


COMPONENTS_ROOT = os.path.join(V2_ROOT, "aligned_components")


def member_multiset(manifest: dict) -> list[str]:
    """The camera-level member list of a fused component.

    A fused manifest's `images` is the UNIQUE basename union of its inputs,
    but the scene holds one camera per input OCCURRENCE - the batcher copies
    overlap images into two zones, so a basename shared by two inputs is two
    cameras (cluster_1: 880 cameras over 537 unique basenames). The true nav
    multiset is the concatenation of the attributed input manifests' members;
    an unfused component is its own multiset.
    """
    inputs = (manifest.get("attribution") or {}).get("inputs") or []
    if not inputs:
        return list(manifest.get("images") or [])
    members: list[str] = []
    for key in inputs:
        zone, comp = key.split("/", 1)
        path = os.path.join(COMPONENTS_ROOT, zone,
                            comp + ".rsalign.manifest.json")
        if not os.path.isfile(path):
            # An input that is itself synthetic (second-round fusion) or
            # missing - fall back to the union rather than half a multiset.
            return list(manifest.get("images") or [])
        members.extend(component_manifest.load_manifest(path).get("images") or [])
    return members


def quantile_ratio_scale(solved: np.ndarray, nav: np.ndarray) -> dict | None:
    """Correspondence-free similarity scale via matched quantiles of
    distance-from-centroid. Returns the stem-oracle's stats shape."""
    if len(solved) < 30 or len(nav) < 30:
        return None
    # Cardinality mismatch (cameras without nav rows, or a lossy fusion)
    # is tolerated up to 5% - quantiles absorb small set differences.
    if abs(len(solved) - len(nav)) / max(len(solved), len(nav)) > 0.05:
        return None
    ds = np.sort(np.linalg.norm(solved - solved.mean(axis=0), axis=1))
    dn = np.sort(np.linalg.norm(nav - nav.mean(axis=0), axis=1))
    q = np.linspace(0.05, 0.95, 91)          # trim tails - outlier cameras
    rs = np.quantile(ds, q)
    rn = np.quantile(dn, q)
    valid = rn > 1e-6
    if valid.sum() < 30:
        return None
    ratios = rs[valid] / rn[valid]
    return {
        "median": float(np.median(ratios)),
        "iqr_low": float(np.quantile(ratios, 0.25)),
        "iqr_high": float(np.quantile(ratios, 0.75)),
        "cameras": int(len(solved)),
    }


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
