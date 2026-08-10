r"""ON2026 run2: unattended per-feature delivery from M:\ON2026_run2.

Owner-authorized fully unattended 2026-08-08 (goal session: features.json
confirmed; ori-accuracy A/B decided by PRE-AUTHORIZED RULE). Chain:

  Z  zoning (Batch Directory, 3D/b_use_z) from nav\flight_log_run2.txt
     + pair repair (ON2026-as-staged names lack the eye token)
  AB orientation-accuracy A/B on one zone (90 vs 10 deg floors, true
     roll) -> rule decides -> zone logs regenerated tight iff adopted
  A  per-zone aligns (fingerprint-aware resume; local:1 frame;
     Division campaign params via RS_ALIGN_PARAMS)
  F  feature assignment (features.json boxes) + ceiling-checked plans
  M  per-feature merges (merge_zones.py, EVERY argument explicit)
  D  per-feature ComputeModel -> finish_model (attach) -> objmetric
  X  DELIVERABLE_MANIFEST.json v0

Driver log grammar (===/ABORT/DONE) at M:\ON2026_run2\logs\driver.log.
Agent workspace: M:\ON2026_run2\_agent (charter discipline).
"""
from __future__ import annotations

import datetime
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import align_fingerprint, feature_merge  # noqa: E402
from modules import component_manifest  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN2 = r"M:\ON2026_run2"
CODE = "ON2026_RH0041_RH2042"
NAV = os.path.join(RUN2, "nav", "flight_log_run2.txt")
EXCLUDE = os.path.join(RUN2, "nav", "excluded_outlier_pairs.txt")
IMAGES = os.path.join(RUN2, "rs_images")
ZONES = os.path.join(RUN2, "batched_images_by_zone")
COMPONENTS = os.path.join(RUN2, "aligned_components")
MERGED = os.path.join(RUN2, "features")
MODELS = os.path.join(RUN2, "models")
LOGS = os.path.join(RUN2, "logs")
AGENT = os.path.join(RUN2, "_agent")
DRIVER_LOG = os.path.join(LOGS, "driver.log")
CONFIG = os.path.join(RUN2, "config")
ALIGN_PARAMS = os.path.join(CONFIG, "ON2026_AlignmentParams.xml")
FEATURES_JSON = os.path.join(CONFIG, "features.json")
LOCAL_TEMPLATE = os.path.join(
    REPO, "modules", "realityscan_interface", "RS_CLI", "Metadata",
    "FlightLogParamsLocal.xml")
SCRIPTS = os.path.join(REPO, "modules", "realityscan_interface", "RS_CLI",
                       "Scripts")
ERRORS_DIR = os.path.join(REPO, "modules", "realityscan_interface", "RS_CLI",
                          "Errors")
COLMAP_STUDIO = r"C:\Users\jonat\Desktop\CoyoteThings\colmap_studio"
SPARSE0 = r"M:\ON2026 COLMAP processing\sparse\0"
SRC_IMAGES = r"M:\ON2026 COLMAP processing\images"

MIN_COMPONENT = 10          # flag-pole pockets (owner: pair 10-15; low end)
MERGE_MIN_SIZE = 10
# OWNER DECISION 2026-08-09 ~08:00: raised from 34,000 (C-20260802-01)
# to pass the hull at 36,441 camera SLOTS - 6,205 of which are
# copy-layout overlap duplicates (30,236 unique images; the pool zone
# layout is the structural fix, queued for the next campaign). Risk
# accepted knowingly: projected ~280 GB peak commit vs the measured
# 319.5 GB commit limit (OOM landed exactly at that limit at 43,847
# cams) - roughly 5% margin; a commit-charge monitor alerts at 290 GB.
CEILING = 37_000
LOSS_TOLERANCE = "0.015"    # measured ON2026 shed 1.06% + headroom; explicit
MIN_FREE_GB = 150.0
NO_WINDOW = 0x08000000

ENV = dict(os.environ)
ENV.update({
    "RS_INSTANCE": "RS1",
    "RS_CACHE_DIR": r"M:\rs_cache",
    "RS_ALIGN_PARAMS": ALIGN_PARAMS,
    "RS_NO_INTERACTIVE": "1",
    "PYTHONIOENCODING": "utf-8",
})


def log(msg):
    line = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} | {msg}"
    print(line, flush=True)
    os.makedirs(LOGS, exist_ok=True)
    with open(DRIVER_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def abort(msg):
    log(f"ABORT: {msg}")
    sys.exit(1)


def run_cmd(name, cmd, log_file, extra_env=None, cwd=REPO):
    log(f"=== {name} starting")
    t0 = time.time()
    env = dict(ENV)
    if extra_env:
        env.update(extra_env)
    with open(log_file, "w", encoding="utf-8") as fh:
        proc = subprocess.run(cmd, cwd=cwd, env=env, stdout=fh,
                              stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL,
                              creationflags=NO_WINDOW)
    mins = (time.time() - t0) / 60
    if proc.returncode != 0:
        abort(f"{name} failed rc={proc.returncode} after {mins:.1f} min - "
              f"see {log_file}")
    log(f"=== {name} finished rc=0 after {mins:.1f} min")


def clear_markers():
    for n in ("errors_RS1.txt", "results_RS1.log"):
        p = os.path.join(ERRORS_DIR, n)
        if os.path.isfile(p):
            os.remove(p)


def sha16(path):
    return (align_fingerprint.sha256_file(path) or "")[:16]


def free_gb():
    return shutil.disk_usage(RUN2).free / 1e9


def guard_disk():
    if free_gb() < MIN_FREE_GB:
        abort(f"M: free space below {MIN_FREE_GB} GB")


# ---------------------------------------------------------------- stage Z

def zone_log_of(zdir):
    logs = glob.glob(os.path.join(zdir, "flight_log*_UTM.txt"))
    return logs[0] if len(logs) == 1 else None


def zone_dirs():
    if not os.path.isdir(ZONES):
        return []
    return sorted((d for d in glob.glob(os.path.join(ZONES, "zone_*"))
                   if os.path.isdir(d)),
                  key=lambda d: int(d.rsplit("_", 1)[1]))


def stage_zoning():
    if zone_dirs():
        log("=== zoning SKIPPED (zones exist)")
        return
    guard_disk()
    run_cmd("zoning (Batch Directory, 3D)", [
        sys.executable, os.path.join(REPO, "main.py"),
        "--output_dir", RUN2, "--continue_automatically", "true",
        "--b_input", IMAGES, "--b_flight_log_path", NAV,
        "--b_target_images", "3000", "--b_min_zone", "1000",
        "--b_max_zone", "4000", "--b_overlap_percent", "20",
        "--b_overlap_max_distance", "10", "--b_use_z", "true",
        "--b_xmp_priors", "false",
    ], os.path.join(LOGS, "zoning.log"),
        extra_env={"RS_MODULES": "Batch Directory"})
    run_cmd("pair repair", [
        sys.executable,
        os.path.join(COLMAP_STUDIO, "pipeline", "pair_repair_zones.py"),
        ZONES, IMAGES, NAV,
    ], os.path.join(LOGS, "pair_repair.log"), cwd=COLMAP_STUDIO)


# --------------------------------------------------------------- stage AB

def regen_master(ori_acc, out_path):
    """Re-export the master log at a given orientation floor via the
    canonical exporter (per-row gimbal widening preserved), outliers
    excluded reproducibly."""
    tmp = os.path.join(AGENT, f"navgen_{ori_acc}")
    os.makedirs(tmp, exist_ok=True)
    run_cmd(f"nav export ori-acc {ori_acc}", [
        sys.executable,
        os.path.join(COLMAP_STUDIO, "pipeline", "export_rs_flightlog.py"),
        SPARSE0, SRC_IMAGES, tmp, "--up-axis=-y",
        "--ori-acc", str(ori_acc), "--exclude-file", EXCLUDE,
    ], os.path.join(LOGS, f"navgen_{ori_acc}.log"), cwd=COLMAP_STUDIO)
    shutil.copy(os.path.join(tmp, "flight_log_local.txt"), out_path)


def filter_log(master_path, names, out_path):
    lines = open(master_path, encoding="utf-8").read().splitlines()
    hdr, rows = lines[0], lines[1:]
    keep = [r for r in rows if r.split(";", 1)[0] in names]
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        f.write(hdr + "\r\n" + "\r\n".join(keep) + "\r\n")
    return len(keep)


def align_zone_into(zone_dir, zone_log, out_root, tag):
    clear_markers()
    run_cmd(f"align {tag}", [
        sys.executable, os.path.join(REPO, "main.py"),
        "--output_dir", out_root, "--continue_automatically", "true",
        "--r_input", zone_dir, "--r_flight_log", zone_log,
        "--r_min_component_size", str(MIN_COMPONENT),
        "--r_project_label", "", "--r_model_generate", "false",
        "--r_model_cull_poly", "false", "--r_model_texture", "false",
        "--r_model_simplify", "false", "--r_display_output", "false",
    ], os.path.join(LOGS, f"align_{tag}.log"),
        extra_env={"RS_MODULES": "RealityScan Alignment"})


def cell_metrics(comp_root, zone_name, zone_log):
    """(registered, components, residual_p95_cm) for one A/B cell."""
    import numpy as np
    zdir = os.path.join(comp_root, "aligned_components", zone_name)
    counts = []
    for mp in glob.glob(os.path.join(zdir, "*.manifest.json")):
        counts.append(json.load(open(mp, encoding="utf-8"))
                      .get("camera_count") or 0)
    prior = {}
    for ln in open(zone_log, encoding="utf-8"):
        p = ln.rstrip("\r\n").split(";")
        if p[0] == "filename" or len(p) < 4:
            continue
        try:
            prior[os.path.splitext(p[0])[0]] = np.array(
                [float(p[1]), float(p[2]), float(p[3])])
        except ValueError:
            continue
    pos_re = re.compile(r"<xcr:Position>([^<]+)</xcr:Position>")
    res = []
    for f in glob.glob(os.path.join(zdir, "identity_r0", "*.xmp")):
        m = pos_re.search(open(f, encoding="utf-8").read())
        stem = os.path.splitext(os.path.basename(f))[0]
        if m and stem in prior:
            solved = np.array([float(v) for v in m.group(1).split()])
            res.append(float(np.linalg.norm(solved - prior[stem])))
    p95 = float(np.percentile(res, 95) * 100) if res else None
    return sum(counts), len(counts), p95


def stage_ab():
    verdict_path = os.path.join(AGENT, "ab_verdict.json")
    if os.path.isfile(verdict_path):
        log("=== ori A/B SKIPPED (verdict exists)")
        return json.load(open(verdict_path, encoding="utf-8"))
    zdirs = zone_dirs()
    if not zdirs:
        abort("no zones for the A/B stage")
    zone_dir = zdirs[0]
    zone_name = os.path.basename(zone_dir)
    zone_log = zone_log_of(zone_dir)
    names = {ln.split(";", 1)[0] for ln in
             open(zone_log, encoding="utf-8") if ";" in ln}
    tight_master = os.path.join(AGENT, "flight_log_ori10_master.txt")
    if not os.path.isfile(tight_master):
        regen_master(10, tight_master)
    tight_zone_log = os.path.join(AGENT, f"{zone_name}_ori10_log.txt")
    filter_log(tight_master, names, tight_zone_log)

    cells = {}
    for tag, zlog in (("ori90", zone_log), ("ori10", tight_zone_log)):
        root = os.path.join(AGENT, f"ab_{tag}")
        if not glob.glob(os.path.join(root, "aligned_components",
                                      zone_name, "*.manifest.json")):
            align_zone_into(zone_dir, zlog, root, f"ab_{tag}_{zone_name}")
        reg, ncomp, p95 = cell_metrics(root, zone_name, zone_log)
        cells[tag] = {"registered": reg, "components": ncomp,
                      "residual_p95_cm": p95}
        log(f"A/B {tag}: registered {reg}, components {ncomp}, "
            f"p95 {p95} cm")

    c90, c10 = cells["ori90"], cells["ori10"]
    adopt_tight = (
        c10["components"] == 1
        and c90["registered"] > 0
        and c10["registered"] >= 0.995 * c90["registered"]
        and (c10["residual_p95_cm"] or 1e9) <= (c90["residual_p95_cm"] or 1e9))
    verdict = {"adopted": "ori10" if adopt_tight else "ori90",
               "rule": "owner pre-authorized 2026-08-08 (ties -> 90)",
               "cells": cells,
               "decided": f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}"}
    json.dump(verdict, open(verdict_path, "w", encoding="utf-8"), indent=2)
    log(f"A/B verdict: {verdict['adopted']}")

    if adopt_tight:
        for zd in zone_dirs():
            zl = zone_log_of(zd)
            znames = {ln.split(";", 1)[0] for ln in
                      open(zl, encoding="utf-8") if ";" in ln}
            filter_log(tight_master, znames, zl + ".tmp")
            os.replace(zl + ".tmp", zl)
        log("zone logs regenerated at the TIGHT orientation floor")
    return verdict


# ---------------------------------------------------------------- stage A

def zone_fingerprint(zone_log):
    return align_fingerprint.build_fingerprint(
        zone_log, LOCAL_TEMPLATE, ALIGN_PARAMS, MIN_COMPONENT)


def stage_aligns():
    for zd in zone_dirs():
        zone_name = os.path.basename(zd)
        zone_log = zone_log_of(zd)
        if zone_log is None:
            abort(f"{zone_name}: expected exactly one flight log")
        out_zone = os.path.join(COMPONENTS, zone_name)
        fp = zone_fingerprint(zone_log)
        if (glob.glob(os.path.join(out_zone, "*.rsalign"))
                and align_fingerprint.matches_current(out_zone, fp)):
            log(f"=== {zone_name} SKIPPED (components match current "
                "nav+settings fingerprint)")
            continue
        guard_disk()
        align_zone_into(zd, zone_log, RUN2, zone_name)


# ---------------------------------------------------------------- stage F

def load_components():
    comps = []
    for mp in sorted(glob.glob(os.path.join(COMPONENTS, "*",
                                            "*.manifest.json"))):
        m = json.load(open(mp, encoding="utf-8"))
        rsalign = mp[:-len(".manifest.json")]
        comps.append({
            "key": component_manifest.component_key(m)
            if hasattr(component_manifest, "component_key")
            else os.path.basename(rsalign),
            "rsalign": rsalign,
            "camera_count": m.get("camera_count") or 0,
            "members": m.get("images") or [],
        })
    return comps


def stage_features():
    plan_path = os.path.join(AGENT, "features_plan.json")
    boxes, default, confirmed = feature_merge.load_feature_boxes(FEATURES_JSON)
    if not confirmed:
        abort("features.json is not confirmed - owner gate")
    comps = load_components()
    if not comps:
        abort("no aligned components found")
    nav = feature_merge.load_nav_positions(NAV)
    assigned = feature_merge.assign_components(comps, nav, boxes, default)
    for c in assigned.get("_unassigned", []):
        log(f"WARNING: component {c['key']} has no nav extent - "
            "NOT delivered under any feature; investigate")
    plans = {}
    for feat, fcomps in assigned.items():
        if feat == "_unassigned" or not fcomps:
            continue
        stages = feature_merge.plan_feature_merge(fcomps, CEILING)
        plans[feat] = {
            "components": [{k: c[k] for k in
                            ("key", "rsalign", "camera_count")}
                           for c in fcomps],
            "total_cameras": sum(c["camera_count"] for c in fcomps),
            "stages": len(stages),
        }
        log(f"feature {feat}: {len(fcomps)} component(s), "
            f"{plans[feat]['total_cameras']:,} cameras")
    json.dump(plans, open(plan_path, "w", encoding="utf-8"), indent=2)
    return plans


# ---------------------------------------------------------------- stage M

def stage_merges(plans):
    results = {}
    for feat, plan in plans.items():
        fdir = os.path.join(MERGED, feat)
        name = f"{CODE}_{feat}"
        report = os.path.join(fdir, "merge_report.json")
        if len(plan["components"]) == 1:
            comp = plan["components"][0]
            results[feat] = {"mode": "single-component",
                             "component": comp["key"],
                             "rsalign": comp["rsalign"]}
            log(f"=== merge {feat} SKIPPED (single component "
                f"{comp['key']} IS the feature)")
            continue
        if os.path.isfile(report):
            log(f"=== merge {feat} SKIPPED (report exists)")
            results[feat] = {"mode": "merged", "report": report}
            continue
        guard_disk()
        os.makedirs(fdir, exist_ok=True)
        complist = os.path.join(fdir, f"{feat}.complist")
        with open(complist, "w", encoding="utf-8", newline="\r\n") as f:
            f.write("\n".join(c["rsalign"] for c in plan["components"])
                    + "\n")
        clear_markers()
        run_cmd(f"merge {feat}", [
            sys.executable, os.path.join(REPO, "merge_zones.py"),
            "--components_root", COMPONENTS, "--images_root", ZONES,
            "--output", fdir, "--name", name, "--complist", complist,
            "--ladder", "merge_first", "--merge_scope", "neighbour",
            "--pair_gate", "overlap", "--loss_tolerance", LOSS_TOLERANCE,
            "--min_size", str(MERGE_MIN_SIZE),
            "--max_scene_cameras", str(CEILING),
            "--auto_model", "false", "--assemble_only", "false",
            "--scale_gate", "true", "--scale_min", "0.9",
            "--scale_max", "1.1", "--visible", "false",
            "--target", "0.9", "--project_label", "",
        ], os.path.join(LOGS, f"merge_{feat}.log"))
        results[feat] = {"mode": "merged", "report": report}
    return results


# ---------------------------------------------------------------- stage D

def find_scene_and_component(feat, merge_result):
    if merge_result["mode"] == "single-component":
        rsalign = merge_result["rsalign"]
        zone_dir = os.path.dirname(rsalign)
        scenes = glob.glob(os.path.join(zone_dir, "*.rsproj"))
        # The zone scene was saved BEFORE the identity loop's in-memory
        # rename, so the component inside the .rsproj does NOT carry the
        # rsalign's zone_N_cK name - selectComponent by that name fails
        # (mesh mast_a, 2026-08-10). "" = maximal component, which for a
        # single-manifest zone IS the feature component.
        return (scenes[0] if scenes else None), ""
    fdir = os.path.join(MERGED, feat)
    scenes = sorted(glob.glob(os.path.join(fdir, "**", "*.rsproj"),
                              recursive=True), key=os.path.getmtime)
    return (scenes[-1] if scenes else None), ""


def stage_models(merge_results):
    for feat, mres in merge_results.items():
        outdir = os.path.join(MODELS, feat)
        final_name = f"{CODE}_{feat}"
        if glob.glob(os.path.join(outdir, final_name + "*.obj")):
            log(f"=== model {feat} SKIPPED (deliverable exists)")
            continue
        guard_disk()
        scene, comp = find_scene_and_component(feat, mres)
        if not scene:
            log(f"WARNING: no scene found for feature {feat} - skipping "
                "model stage; investigate")
            continue
        os.makedirs(outdir, exist_ok=True)
        model_name = f"{final_name}_HighPoly"
        clear_markers()
        # hull @ depth-map downscale 2 (2026-08-10): the full-res hull
        # mesh needs ~1.4+ TB of depth-map cache and exhausted M:
        # (0x80070070, the historical hull-model killer; no volume on
        # this box fits full res). ds2 ~= quarter footprint; texture
        # stays 4x8k from full-res images. A full-res re-mesh later is
        # purely additive - the merged component persists.
        mesh_env = {"RS_MESH_DETAIL": "normal"} if feat == "hull" else None
        run_cmd(f"mesh {feat}", [
            os.path.join(SCRIPTS, "ComputeModel.bat"),
            scene, comp, model_name,
        ], os.path.join(LOGS, f"mesh_{feat}.log"), extra_env=mesh_env)
        run_cmd(f"finish {feat}", [
            sys.executable, os.path.join(REPO, "finish_model.py"),
            "--instance", "RS1", "--outdir", outdir, "--name", final_name,
            "--preset", "4x8k", "--simplify", "true",
            "--format", "objmetric", "--source-model", model_name,
            "--save-path", scene,
        ], os.path.join(LOGS, f"finish_{feat}.log"))
        subprocess.run([os.path.join("C:\\", "Program Files", "Epic Games",
                                     "RealityScan_2.2", "RealityScan.exe"),
                        "-delegateTo", "RS1", "-quit"],
                       creationflags=NO_WINDOW)
        time.sleep(10)


# ---------------------------------------------------------------- stage X

def stage_manifest(ab_verdict, plans, merge_results):
    manifest = {
        "schema": 0,
        "campaign": CODE,
        "created": f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}",
        "coordinate_frame": {
            "name": "local Z-up Euclidean (local:1)",
            "absolute_georeference": "none - local frame; UTM via USBL "
                                     "fit available later (owner Q3b)",
            "nav_source": "COLMAP sparse/0 master solution",
            "nav_file": NAV, "nav_sha256_16": sha16(NAV),
        },
        "settings": {
            "alignment_params": ALIGN_PARAMS,
            "alignment_sha256_16": sha16(ALIGN_PARAMS),
            "orientation_ab": ab_verdict,
            "min_component_size": MIN_COMPONENT,
            "merge": {"ladder": "merge_first", "loss_tolerance":
                      LOSS_TOLERANCE, "ceiling": CEILING},
        },
        "features": {},
    }
    for feat, plan in plans.items():
        deliv = sorted(glob.glob(os.path.join(MODELS, feat, "*.obj")))
        manifest["features"][feat] = {
            "components": plan["components"],
            "total_cameras": plan["total_cameras"],
            "merge": merge_results.get(feat, {}),
            "deliverables": [{"path": p, "bytes": os.path.getsize(p)}
                             for p in deliv],
        }
    path = os.path.join(MODELS, "DELIVERABLE_MANIFEST.json")
    os.makedirs(MODELS, exist_ok=True)
    json.dump(manifest, open(path, "w", encoding="utf-8"), indent=2)
    log(f"manifest written: {path}")


def main():
    for d in (LOGS, AGENT, MERGED, MODELS):
        os.makedirs(d, exist_ok=True)
    log(f"driver start: {CODE} from {RUN2} (unattended, owner-authorized "
        "2026-08-08)")
    guard_disk()
    stage_zoning()
    ab = stage_ab()
    stage_aligns()
    plans = stage_features()
    merges = stage_merges(plans)
    stage_models(merges)
    stage_manifest(ab, plans, merges)
    log("driver DONE")


if __name__ == "__main__":
    main()
