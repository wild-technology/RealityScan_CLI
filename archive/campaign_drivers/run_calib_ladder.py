r"""ON2026 calibration ladder (owner directives 2026-08-08).

Re-test of the calibration-prior question after the first cell was
invalidated by two confounds (sidecar hygiene collision + shared
M:\rs_cache), and after the owner's field finding that same-name XMP
sidecar AUTO-IMPORT is unreliable: every cell here delivers calibration
through EXPLICIT commands (FINDINGS.md 2026-08-08), on the quiet RS2
instance with its own cache, while production run2 continues on RS1.

One variable per rung:
  A  control      - no calibration input at all (harness + cache-isolation
                    validation; oracle = production zone_1@20k)
  B  groups       - per-eye PRIOR calibration+lens groups only
                    (-selectImage + -setPriorCalibrationGroup/-setPriorLensGroup)
  C  xmp          - groups AND manufacturer approximate intrinsics via
                    -addImageWithCalibration (whole paths, xmps in a
                    separate directory; content from camera_registry)

Detector (verified against the failed cell's harvest before launch):
census over harvested identity XMPs - registration/components from
manifests, solved FocalLength35mm distribution, CalibrationGroup
distribution. A groups-cell whose regex matched nothing shows up as an
ungrouped census, never as a silent pass.

Budget: ~50 min/cell, ~3 h total. Aborts: cell rc!=0, disk < 150 GB.
Verdict: M:\ON2026_run2\_agent\calib_ladder\ladder_verdict.json.
"""
from __future__ import annotations

import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import camera_registry  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN2 = r"M:\ON2026_run2"
AGENT = os.path.join(RUN2, "_agent")
LADDER = os.path.join(AGENT, "calib_ladder")
TREE = os.path.join(AGENT, "calib_zone1")          # rs_images + zone log
IMAGES = os.path.join(TREE, "rs_images")
ZONE_LOG = os.path.join(TREE, "flight_log_UTM.txt")  # staged names, local frame, ori10
ALIGN_PARAMS = os.path.join(RUN2, "config", "ON2026_AlignmentParams.xml")
ERRORS_DIR = os.path.join(REPO, "modules", "realityscan_interface", "RS_CLI",
                          "Errors")
DRIVER_LOG = os.path.join(LADDER, "ladder.log")
EXPECTED_IMAGES = 3626
MIN_COMPONENT = 10
MIN_FREE_GB = 150.0
NO_WINDOW = 0x08000000

# Production oracle: zone_1 @20k on RS1 (driver.log 2026-08-08)
ORACLE = {"registered": 3545, "total": 3626, "components": 1}

ENV = dict(os.environ)
ENV.update({
    "RS_INSTANCE": "RS2",
    "RS_CACHE_DIR": r"M:\rs_cache_rs2",
    "RS_ALIGN_PARAMS": ALIGN_PARAMS,
    "RS_ALIGN_SCRIPT": "CalibCellAlign.bat",
    "RS_NO_INTERACTIVE": "1",
    "PYTHONIOENCODING": "utf-8",
    "RS_MODULES": "RealityScan Alignment",
})
# The auto-sidecar env gate stays UNSET: delivery is explicit commands.
ENV.pop("RS_VOYIS_CALIB_SIDECARS", None)


def log(msg):
    line = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} | {msg}"
    print(line, flush=True)
    os.makedirs(LADDER, exist_ok=True)
    with open(DRIVER_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def abort(msg):
    log(f"ABORT: {msg}")
    sys.exit(1)


def clear_markers():
    for n in ("errors_RS2.txt", "results_RS2.log"):
        p = os.path.join(ERRORS_DIR, n)
        if os.path.isfile(p):
            os.remove(p)


# ------------------------------------------------------------------ census

FOCAL_RE = re.compile(r'xcr:FocalLength35mm="([^"]+)"|'
                      r"<xcr:FocalLength35mm>([^<]+)</xcr:FocalLength35mm>")
GROUP_RE = re.compile(r'xcr:CalibrationGroup="([^"]+)"|'
                      r"<xcr:CalibrationGroup>([^<]+)</xcr:CalibrationGroup>")
POS_RE = re.compile(r"<xcr:Position>([^<]+)</xcr:Position>|"
                    r'xcr:Position="([^"]+)"')


def census(cell_out, zone_name):
    """Registration/component counts from manifests; solved-focal and
    calibration-group distributions plus prior-position residuals from
    the harvested identity XMPs."""
    import numpy as np
    zdir = os.path.join(cell_out, "aligned_components", zone_name)
    counts = []
    for mp in glob.glob(os.path.join(zdir, "*.manifest.json")):
        counts.append(json.load(open(mp, encoding="utf-8"))
                      .get("camera_count") or 0)
    prior = {}
    for ln in open(ZONE_LOG, encoding="utf-8"):
        p = ln.rstrip("\r\n").split(";")
        if p[0] == "filename" or len(p) < 4:
            continue
        try:
            prior[os.path.splitext(p[0])[0]] = np.array(
                [float(p[1]), float(p[2]), float(p[3])])
        except ValueError:
            continue
    focals, groups, res = [], {}, []
    for f in glob.glob(os.path.join(zdir, "identity_r*", "*.xmp")):
        t = open(f, encoding="utf-8", errors="replace").read()
        m = FOCAL_RE.search(t)
        if m:
            try:
                focals.append(float(m.group(1) or m.group(2)))
            except ValueError:
                pass
        m = GROUP_RE.search(t)
        g = (m.group(1) or m.group(2)) if m else "ABSENT"
        groups[g] = groups.get(g, 0) + 1
        m = POS_RE.search(t)
        stem = os.path.splitext(os.path.basename(f))[0]
        if m and stem in prior:
            solved = np.array([float(v)
                               for v in (m.group(1) or m.group(2)).split()])
            res.append(float(np.linalg.norm(solved - prior[stem])))
    out = {
        "registered": sum(counts),
        "components": len(counts),
        "residual_p95_cm": (float(np.percentile(res, 95) * 100)
                            if res else None),
        "residual_median_cm": (float(np.median(res) * 100) if res else None),
        "solved_focal_min": min(focals) if focals else None,
        "solved_focal_median": (float(np.median(focals)) if focals else None),
        "solved_focal_max": max(focals) if focals else None,
        "focal_samples": len(focals),
        "calibration_groups": groups,
    }
    return out


# ------------------------------------------------------------------ cells

def purge_tree_xmps():
    n = 0
    for f in glob.glob(os.path.join(IMAGES, "**", "*.xmp"), recursive=True):
        os.remove(f)
        n += 1
    return n


# Grouping-only XMP: CalibrationGroup/DistortionGroup and nothing else.
# Cell B isolates the per-eye-grouping variable from the prior VALUES;
# both cells use the SAME validated delivery (-addImageWithCalibration,
# probe 4 - the setPrior* commands are silently non-functional from the
# CLI, FINDINGS 2026-08-08).
GROUPS_ONLY_XMP = (
    '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
    '  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
    '    <rdf:Description xcr:Version="4"\n'
    '       xcr:CalibrationGroup="{group}" xcr:DistortionGroup="{group}"\n'
    '       xmlns:xcr="http://www.capturingreality.com/ns/xcr/1.1#">\n'
    '    </rdf:Description>\n'
    '  </rdf:RDF>\n'
    '</x:xmpmeta>\n')


def build_xmp_inputs(kind):
    """Registry XMPs in a SEPARATE directory + a .rscmd command file
    (one -addImageWithCalibration per image, whole paths, unquoted -
    no path here contains spaces, asserted below).

    kind 'groups': CalibrationGroup/DistortionGroup only (cell B).
    kind 'full':   complete approximate manufacturer priors (cell C).
    """
    xmp_dir = os.path.join(LADDER, f"xmp_{kind}")
    os.makedirs(xmp_dir, exist_ok=True)
    rscmd = os.path.join(LADDER, f"add_with_calibration_{kind}.rscmd")
    lines = [f"# built by run_calib_ladder.py ({kind}) - one explicit"
             " image+calibration add per line"]
    n_l = n_r = 0
    for img in sorted(glob.glob(os.path.join(IMAGES, "*.jpg"))):
        base = os.path.basename(img)
        cam = camera_registry.identify(base)
        if cam is None or not cam.key.startswith("voyis_"):
            abort(f"unidentified image in the calib tree: {base}")
        if " " in img:
            abort(f"space in image path (rscmd quoting hazard): {img}")
        if kind == "full":
            content = camera_registry.calibration_xmp(cam)
        else:
            content = GROUPS_ONLY_XMP.format(group=cam.calibration_group)
        xmp_path = os.path.join(xmp_dir, os.path.splitext(base)[0] + ".xmp")
        with open(xmp_path, "w", encoding="utf-8") as f:
            f.write(content)
        lines.append(f"-addImageWithCalibration {img} {xmp_path}")
        if cam.key == "voyis_left":
            n_l += 1
        else:
            n_r += 1
    with open(rscmd, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")
    if n_l + n_r != EXPECTED_IMAGES:
        abort(f"{kind} build: {n_l}+{n_r} != {EXPECTED_IMAGES}")
    log(f"{kind} inputs: {n_l} L + {n_r} R xmps in {xmp_dir}")
    return rscmd


def run_cell(tag, extra_env):
    out_root = os.path.join(LADDER, f"cell{tag}")
    zdir = os.path.join(out_root, "aligned_components", "calib_zone1")
    if glob.glob(os.path.join(zdir, "*.manifest.json")):
        log(f"=== cell {tag} SKIPPED (manifests exist)")
        return census(out_root, "calib_zone1")
    if shutil.disk_usage(RUN2).free / 1e9 < MIN_FREE_GB:
        abort("M: free space below floor")
    os.makedirs(out_root, exist_ok=True)
    purged = purge_tree_xmps()
    if purged:
        log(f"purged {purged} leftover .xmp from the image tree")
    clear_markers()
    log(f"=== cell {tag} align starting")
    t0 = time.time()
    env = dict(ENV)
    env.update(extra_env)
    log_file = os.path.join(LADDER, f"cell{tag}_align.log")
    with open(log_file, "w", encoding="utf-8") as fh:
        proc = subprocess.run(
            [sys.executable, os.path.join(REPO, "main.py"),
             "--output_dir", out_root, "--continue_automatically", "true",
             "--r_input", TREE, "--r_flight_log", ZONE_LOG,
             "--r_min_component_size", str(MIN_COMPONENT),
             "--r_project_label", "", "--r_model_generate", "false",
             "--r_model_cull_poly", "false", "--r_model_texture", "false",
             "--r_model_simplify", "false", "--r_display_output", "false"],
            cwd=REPO, env=env, stdout=fh, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    mins = (time.time() - t0) / 60
    if proc.returncode != 0:
        abort(f"cell {tag} failed rc={proc.returncode} after {mins:.1f} min "
              f"- see {log_file}")
    log(f"=== cell {tag} align finished rc=0 after {mins:.1f} min")
    c = census(out_root, "calib_zone1")
    log(f"cell {tag} census: {json.dumps(c, sort_keys=True)}")
    return c


def main():
    os.makedirs(LADDER, exist_ok=True)
    os.makedirs(r"M:\rs_cache_rs2", exist_ok=True)
    jpgs = len(glob.glob(os.path.join(IMAGES, "*.jpg")))
    if jpgs != EXPECTED_IMAGES:
        abort(f"tree has {jpgs} jpgs, expected {EXPECTED_IMAGES}")
    if not os.path.isfile(ZONE_LOG):
        abort(f"zone log missing: {ZONE_LOG}")
    if not os.path.isfile(ALIGN_PARAMS):
        abort(f"alignment params missing: {ALIGN_PARAMS}")

    # Detector liveness (verification standard #1): the census parser
    # must produce non-trivial output on the FAILED cell's harvest
    # (known-bad oracle) before any new cell trusts it.
    old = os.path.join(AGENT, "calib_test")
    if os.path.isdir(os.path.join(old, "aligned_components", "calib_zone1")):
        probe = census(old, "calib_zone1")
        log(f"detector probe on failed cell: {json.dumps(probe, sort_keys=True)}")
        if not probe["registered"] or not probe["focal_samples"]:
            abort("census detector failed its liveness probe")

    verdict = {"oracle_production_zone1_20k": ORACLE, "cells": {}}
    verdict["cells"]["A_control"] = run_cell("A", {"RS_CALIB_MODE": ""})
    rscmd_g = build_xmp_inputs("groups")
    verdict["cells"]["B_groups_xmp"] = run_cell(
        "B", {"RS_CALIB_MODE": "xmp", "RS_CALIB_XMP_RSCMD": rscmd_g})
    rscmd_f = build_xmp_inputs("full")
    verdict["cells"]["C_full_xmp"] = run_cell(
        "C", {"RS_CALIB_MODE": "xmp", "RS_CALIB_XMP_RSCMD": rscmd_f})

    with open(os.path.join(LADDER, "ladder_verdict.json"), "w",
              encoding="utf-8") as f:
        json.dump(verdict, f, indent=2, sort_keys=True)
    log("DONE - verdict at ladder_verdict.json (adoption decision is the "
        "coordinator's, by the recorded rule)")


if __name__ == "__main__":
    main()
