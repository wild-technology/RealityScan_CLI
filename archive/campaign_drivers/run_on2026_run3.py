r"""ON2026 run3: owner-directed campaign from M:\ON2026_run3 (2026-08-28).

Owner directives (all mandatory, charter: M:\ON2026_run3\RUN_CHARTER.md):
  - zones <= 10,000 images, Z-aware 3D zoning (C-20260730-06), POOL layout
    (canonical pool + full-path logs + .imagelist - FLIGHTLOG_ARCHITECTURE)
  - per-eye calibration groups L/R with the COLMAP-solved PINHOLE
    intrinsics, delivered via the VALIDATED channel: per-image XMPs in a
    separate dir + -addImageWithCalibration rscmd (calibration_sidecars
    mechanics; -setPriorCalibrationGroup does NOT stick from the CLI)
  - flight log with Euler angles from the PINNED-convention exporter math
    (C-20260827-10), GLOBAL position accuracy 0.5 m, ori floor 10 deg
  - frame: LOCAL:1 fallback (UTM gates FAILED - USBL ~4.9 m median
    residual, per-dive scale 0.94/0.83; see nav\nav_fit.json). The local
    frame is gravity-Z-up + TRUE-NORTH +Y (nav azimuth), metric 1.0.
  - align: Brown3 (owner order; C-20260730-09 context recorded), High
    sensitivity, 20k features, georef-merge on
  - per-zone aligns -> grow -> merges, HONORING the 34,000-camera merge
    ceiling (C-20260802-01 INVARIANT): primary = adjacency-greedy maximal
    union under the ceiling; remainder merged separately. NO full-38.9k
    merge scene.
  - NO model stage in run3 (owner runs dense/meshing separately).

Fixture-first (rule 7): stage FX aligns the 30-pair fixture through the
COMPLETE new path (pool + rscmd calibration + Euler log + Brown3) and
gates on 1 component / >=58 of 60 / rig baseline within 1.5%% / per-eye
groups present. ABORT on failure - the calibration CONTENT here is
numerically identical to ladder arm C (the COLMAP solve fixed intrinsics
to the resized-corrected values), which COLLAPSED registration under
Division+0.02 m priors; this cell differs (Brown3, 0.5 m accuracies,
explicit adds) and the fixture decides.

Driver log grammar (===/ABORT/DONE) at M:\ON2026_run3\logs\driver.log.
Resume: every stage is fingerprint/existence-gated; re-run the task.
ASCII-only console output.
"""
from __future__ import annotations

import ctypes
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

from modules import align_fingerprint, calibration_sidecars  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN3 = r"M:\ON2026_run3"
CODE = "ON2026_RH0041_RH0042"   # dive codes VERIFIED from raw nav trees
                                # (RH0041=06-21, RH0042=06-22); run2's
                                # "RH2042" was the unverified spelling.
POOL = os.path.join(RUN3, "pool")
RS_IMAGES = os.path.join(POOL, "rs_images")
MASTER_LOG = os.path.join(POOL, "flight_log_local.txt")
ZONES = os.path.join(RUN3, "batched_images_by_zone")
COMPONENTS = os.path.join(RUN3, "aligned_components")
GROWN = os.path.join(RUN3, "grown")
MERGED = os.path.join(RUN3, "merged")
LOGS = os.path.join(RUN3, "logs")
AGENT = os.path.join(RUN3, "_agent")
CONFIG = os.path.join(RUN3, "config")
DRIVER_LOG = os.path.join(LOGS, "driver.log")
HEARTBEAT = os.path.join(LOGS, "driver_heartbeat.txt")
ALIGN_PARAMS = os.path.join(CONFIG, "ON2026_run3_AlignmentParams.xml")
ALIGN_BAT = os.path.join(AGENT, "tools", "Run3PoolCalibAlign.bat")
XMP_DIR = os.path.join(CONFIG, "calib_xmp")
RSCMD_DIR = os.path.join(CONFIG, "rscmd")
FIXTURE_IMAGES = r"M:\ON2026_fixture\images"
LOCAL_TEMPLATE = os.path.join(
    REPO, "modules", "realityscan_interface", "RS_CLI", "Metadata",
    "FlightLogParamsLocal.xml")
ERRORS_DIR = os.path.join(REPO, "modules", "realityscan_interface", "RS_CLI",
                          "Errors")
RS_EXE = r"C:\Program Files\Epic Games\RealityScan_2.2\RealityScan.exe"

# COLMAP-solved PINHOLE intrinsics, sparse\0 cameras.bin (verified
# 2026-08-28; IDENTICAL for both eyes - the solve fixed intrinsics to the
# resized-corrected values; numerically equal to cameras.json voyis_*).
INTRINSICS = [[1895.6747569500258, 0.0, 1444.9779663085938],
              [0.0, 1895.6747569500258, 1386.6773681640625],
              [0.0, 0.0, 1.0]]
RESOLUTION = (2816, 2816)
DISTORTION = "brown3"           # matches the ordered Brown3 align model
BASELINE_ORACLE = 0.16970

ZONE_CAP = 10_000               # owner directive: zones <= 10,000 images
CEILING = 34_000                # C-20260802-01 ABSOLUTE merge-scene wall
MIN_COMPONENT = 10
MERGE_MIN_SIZE = 10
LOSS_TOLERANCE = "0.015"
MIN_FREE_GB = 150.0
COMMIT_HEADROOM_GB = 60.0       # required (limit - current commit) slack
CASPAR_WAIT_CAP_S = 4 * 3600
NO_WINDOW = 0x08000000

ENV = dict(os.environ)
ENV.update({
    "RS_INSTANCE": "RS3",
    "RS_CACHE_DIR": r"M:\rs_cache_rs3",
    "RS_ALIGN_PARAMS": ALIGN_PARAMS,
    "RS_NO_INTERACTIVE": "1",
    "RS_HEADLESS": "1",
    "PYTHONIOENCODING": "utf-8",
})
ENV.pop("RS_VOYIS_CALIB_SIDECARS", None)   # explicit-command delivery only

ALIGN_ENV = {
    "RS_MODULES": "RealityScan Alignment",
    "RS_ALIGN_POOL_DIR": RS_IMAGES,
    "RS_ALIGN_SCRIPT": ALIGN_BAT,
    "RS_CALIB_MODE": "xmp",
}


def log(msg):
    line = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} | {msg}"
    print(line, flush=True)
    os.makedirs(LOGS, exist_ok=True)
    with open(DRIVER_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    with open(HEARTBEAT, "w", encoding="utf-8") as f:
        f.write(f"{time.time():.0f}\n")


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
    for n in ("errors_RS3.txt", "results_RS3.log"):
        p = os.path.join(ERRORS_DIR, n)
        if os.path.isfile(p):
            os.remove(p)


def free_gb():
    return shutil.disk_usage(RUN3).free / 1e9


def guard_disk():
    if free_gb() < MIN_FREE_GB:
        abort(f"M: free space below {MIN_FREE_GB} GB")


def commit_state_gb():
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    st = MEMORYSTATUSEX()
    st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
    limit = st.ullTotalPageFile / 1e9
    used = (st.ullTotalPageFile - st.ullAvailPageFile) / 1e9
    return limit, used


def purge_pool_pose_xmps():
    """Pool hygiene: stale pose sidecars auto-import as exact priors (B7)."""
    n = 0
    for f in glob.glob(os.path.join(RS_IMAGES, "*.xmp")):
        os.remove(f)
        n += 1
    if n:
        log(f"purged {n} leftover .xmp from the pool")


# --------------------------------------------------------------- stage N0

def stage_preflight():
    for p, why in ((RS_IMAGES, "pool"), (MASTER_LOG, "master log"),
                   (ALIGN_PARAMS, "align params"), (ALIGN_BAT, "align .bat"),
                   (RS_EXE, "RealityScan exe"),
                   (os.path.join(RUN3, "nav", "frame_of_record.json"),
                    "frame of record")):
        if not os.path.exists(p):
            abort(f"preflight: {why} missing: {p}")
    n_pool = len(glob.glob(os.path.join(RS_IMAGES, "*.jpg")))
    if n_pool != 38_924:
        abort(f"preflight: pool holds {n_pool} images, expected 38,924")
    guard_disk()
    limit, used = commit_state_gb()
    log(f"preflight OK: pool 38,924; disk free {free_gb():.0f} GB; "
        f"commit {used:.0f}/{limit:.0f} GB")
    os.makedirs(r"M:\rs_cache_rs3", exist_ok=True)
    if "Brown3" not in open(ALIGN_PARAMS, encoding="utf-8").read():
        abort("preflight: align params do not pin Brown3")


# --------------------------------------------------------------- stage C

# Calibration ARM (config\calib_arm.json {"arm": "values"|"groups"}):
#   values - per-eye groups + COLMAP-solved intrinsics (the ORDERED arm).
#            Fixture 2026-08-28: 60/60 but baseline -2.55% and focal
#            steered 24.23 -> 25.7 while the no-calib control held +0.21%
#            - metric gate FAILED, campaign aborted per the owner rule.
#   groups - groups-only XMPs, no values (ladder B shape). Fixture cell:
#            60/60, 1 comp, baseline -0.09% - PASSES all gates.
# Switching arms after zones aligned is refused (campaign_arm guard).
GROUPS_ONLY_XMP = (
    '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
    '  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
    '    <rdf:Description xcr:Version="4"\n'
    '       xcr:CalibrationGroup="{group}" xcr:DistortionGroup="{group}"\n'
    '       xmlns:xcr="http://www.capturingreality.com/ns/xcr/1.1#">\n'
    '    </rdf:Description>\n'
    '  </rdf:RDF>\n'
    '</x:xmpmeta>\n')


def calib_arm():
    path = os.path.join(CONFIG, "calib_arm.json")
    if not os.path.isfile(path):
        return "values"                      # the ordered default
    arm = json.load(open(path, encoding="utf-8")).get("arm", "values")
    if arm not in ("values", "groups"):
        abort(f"calib_arm.json: unknown arm {arm!r}")
    return arm


def guard_campaign_arm(arm):
    """An arm switch invalidates every aligned zone (the align fingerprint
    does not cover the rscmd content) - refuse silently mixed campaigns."""
    rec_path = os.path.join(AGENT, "campaign_arm.json")
    if os.path.isfile(rec_path):
        rec = json.load(open(rec_path, encoding="utf-8")).get("arm")
        if rec != arm and glob.glob(os.path.join(COMPONENTS, "*",
                                                 "*.rsalign")):
            abort(f"calibration arm switched {rec!r} -> {arm!r} with "
                  "aligned components on disk - supersede/clear "
                  "aligned_components (and grown/) first; mixed-arm "
                  "merges are not comparable")
    json.dump({"arm": arm}, open(rec_path, "w", encoding="utf-8"))


def eye_xmp_path(pool_name, arm):
    return os.path.join(XMP_DIR + "_" + arm,
                        os.path.splitext(pool_name)[0] + ".xmp")


def stage_calibration_inputs(arm):
    xdir = XMP_DIR + "_" + arm
    os.makedirs(xdir, exist_ok=True)
    vals = calibration_sidecars.intrinsics_to_xmp_values(INTRINSICS,
                                                         RESOLUTION)
    pool = sorted(os.path.basename(p) for p in
                  glob.glob(os.path.join(RS_IMAGES, "*.jpg")))
    existing = len(glob.glob(os.path.join(xdir, "*.xmp")))
    if existing == len(pool):
        log(f"=== calibration XMPs SKIPPED ({existing} exist, arm={arm})")
        return
    n = {"L": 0, "R": 0}
    for name in pool:
        eye = calibration_sidecars.eye_of(name)
        if eye is None:
            abort(f"pool image with no eye token: {name}")
        group = 0 if eye == "L" else 1
        if arm == "groups":
            xmp = GROUPS_ONLY_XMP.format(group=group)
        else:
            xmp = calibration_sidecars.XMP_TEMPLATE.format(
                prior="approximate", group=group,
                distortion=DISTORTION, focal35=f"{vals['focal35']:.10f}",
                ppu=f"{vals['ppu']:.10f}", ppv=f"{vals['ppv']:.10f}")
        with open(eye_xmp_path(name, arm), "w", encoding="utf-8") as f:
            f.write(xmp)
        n[eye] += 1
    log(f"calibration XMPs written (arm={arm}): {n['L']} L + {n['R']} R "
        f"(groups L=0/R=1)")


def build_rscmd(tag, image_paths, arm):
    os.makedirs(RSCMD_DIR, exist_ok=True)
    rscmd = os.path.join(RSCMD_DIR, f"{tag}_{arm}.rscmd")
    lines = [f"# run3 {tag} (arm={arm}): explicit image+calibration adds"]
    for img in image_paths:
        if " " in img:
            abort(f"space in image path (rscmd quoting hazard): {img}")
        xmp = eye_xmp_path(os.path.basename(img), arm)
        if not os.path.isfile(xmp):
            abort(f"missing calibration xmp for {img}")
        lines.append(f"-addImageWithCalibration {img} {xmp}")
    with open(rscmd, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")
    return rscmd


# --------------------------------------------------------------- stage FX

def read_positions(identity_dir):
    pos_re = re.compile(r"<xcr:Position>([^<]+)</xcr:Position>|"
                        r'xcr:Position="([^"]+)"')
    out = {}
    for f in glob.glob(os.path.join(identity_dir, "*.xmp")):
        t = open(f, encoding="utf-8", errors="replace").read()
        m = pos_re.search(t)
        if m:
            vals = [float(v) for v in (m.group(1) or m.group(2)).split()]
            out[os.path.splitext(os.path.basename(f))[0]] = vals
    return out


def group_census(identity_root):
    g_re = re.compile(r'xcr:CalibrationGroup="([^"]+)"|'
                      r"<xcr:CalibrationGroup>([^<]+)</xcr:CalibrationGroup>")
    groups = {}
    for f in glob.glob(os.path.join(identity_root, "identity_r*", "*.xmp")):
        t = open(f, encoding="utf-8", errors="replace").read()
        m = g_re.search(t)
        g = (m.group(1) or m.group(2)) if m else "ABSENT"
        groups[g] = groups.get(g, 0) + 1
    return groups


def stage_fixture(arm):
    verdict_path = os.path.join(AGENT, "fixture_verdict.json")
    if os.path.isfile(verdict_path):
        v = json.load(open(verdict_path, encoding="utf-8"))
        if v.get("verdict") == "PASS":
            log("=== fixture probe SKIPPED (verdict PASS exists)")
            return
        abort("fixture verdict exists and is not PASS - resolve before "
              "re-running (delete fixture_verdict.json to retry)")
    stems = sorted(os.path.splitext(os.path.basename(p))[0] for p in
                   glob.glob(os.path.join(FIXTURE_IMAGES, "rig", "left",
                                          "*.jpg")))
    if len(stems) != 30:
        abort(f"fixture: expected 30 left stems, found {len(stems)}")
    members = []
    for s in stems:
        for eye in ("L_", "R_"):
            p = os.path.join(RS_IMAGES, f"{eye}{s}.jpg")
            if not os.path.isfile(p):
                abort(f"fixture member missing from pool: {p}")
            members.append(p)
    fzone = os.path.join(AGENT, "fixture", "zones", "zone_fx")
    os.makedirs(fzone, exist_ok=True)
    with open(os.path.join(fzone, "zone_fx.imagelist"), "w",
              encoding="utf-8", newline="") as f:
        f.write("\r\n".join(members) + "\r\n")
    keep = set(members)
    rows = [ln for ln in open(MASTER_LOG, encoding="utf-8").read()
            .splitlines()[1:] if ln.split(";", 1)[0] in keep]
    if len(rows) != 60:
        abort(f"fixture: {len(rows)} master-log rows matched, expected 60")
    hdr = open(MASTER_LOG, encoding="utf-8").readline().rstrip("\r\n")
    flog = os.path.join(fzone, "flight_log_UTM.txt")   # untagged -> local
    with open(flog, "w", encoding="utf-8", newline="") as f:
        f.write(hdr + "\r\n" + "\r\n".join(rows) + "\r\n")
    rscmd = build_rscmd("zone_fx", members, arm)
    purge_pool_pose_xmps()
    clear_markers()
    out_root = os.path.join(AGENT, "fixture")
    run_cmd("fixture align (pool+calib+Brown3+Euler)", [
        sys.executable, os.path.join(REPO, "main.py"),
        "--output_dir", out_root, "--continue_automatically", "true",
        "--r_input", fzone, "--r_flight_log", flog,
        "--r_min_component_size", str(MIN_COMPONENT),
        "--r_project_label", "", "--r_model_generate", "false",
        "--r_model_cull_poly", "false", "--r_model_texture", "false",
        "--r_model_simplify", "false", "--r_display_output", "false",
    ], os.path.join(LOGS, "fixture_align.log"),
        extra_env=dict(ALIGN_ENV, RS_CALIB_XMP_RSCMD=rscmd))

    zdir = os.path.join(out_root, "aligned_components", "zone_fx")
    manifests = glob.glob(os.path.join(zdir, "*.manifest.json"))
    counts = [json.load(open(m, encoding="utf-8")).get("camera_count") or 0
              for m in manifests]
    pos = read_positions(os.path.join(zdir, "identity_r0"))
    baselines = []
    for s in stems:
        a, b = pos.get(f"L_{s}"), pos.get(f"R_{s}")
        if a and b:
            baselines.append(sum((x - y) ** 2
                                 for x, y in zip(a, b)) ** 0.5)
    baselines.sort()
    med_b = baselines[len(baselines) // 2] if baselines else None
    groups = group_census(zdir)
    # Harvest signatures per ladder + run3 cell precedent (2026-08-28):
    # value XMPs always harvest as {-1: N} (per-image calibration);
    # groups-only XMPs harvest as ONE merged group id (never per-eye);
    # per-eye ids do not survive to the final state on ANY channel.
    if arm == "values":
        sig_ok = set(groups) == {"-1"}
    else:
        sig_ok = (len(groups) == 1
                  and next(iter(groups)) not in ("-1", "ABSENT"))
    gates = {
        "one_component": len(counts) == 1,
        "registered_ge_58": sum(counts) >= 58,
        "baseline_within_1p5pct": (med_b is not None and
                                   abs(med_b - BASELINE_ORACLE)
                                   / BASELINE_ORACLE <= 0.015),
        "calibration_signature": sig_ok,
    }
    verdict = {"verdict": "PASS" if all(gates.values()) else "FAIL",
               "arm": arm,
               "gates": gates, "components": counts,
               "registered": sum(counts),
               "baseline_median_m": med_b, "baseline_pairs": len(baselines),
               "calibration_groups": groups,
               "decided": f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}"}
    json.dump(verdict, open(verdict_path, "w", encoding="utf-8"), indent=2)
    log(f"fixture verdict: {json.dumps(verdict)}")
    if verdict["verdict"] != "PASS":
        abort("FIXTURE GATES FAILED - new-settings import chain does not "
              "produce a 1-component metric align; campaign stopped "
              "(owner rule). Evidence: fixture_verdict.json + "
              "logs/fixture_align.log")


# --------------------------------------------------------------- stage Z

def zone_dirs():
    if not os.path.isdir(ZONES):
        return []
    return sorted((d for d in glob.glob(os.path.join(ZONES, "zone_*"))
                   if os.path.isdir(d)),
                  key=lambda d: int(d.rsplit("_", 1)[1]))


def zone_log_of(zdir):
    logs = glob.glob(os.path.join(zdir, "flight_log*_UTM.txt"))
    return logs[0] if len(logs) == 1 else None


def zone_list_of(zdir):
    lists = glob.glob(os.path.join(zdir, "*.imagelist"))
    return lists[0] if len(lists) == 1 else None


def stage_zoning():
    if zone_dirs():
        log("=== zoning SKIPPED (zones exist)")
        return
    guard_disk()
    run_cmd("zoning (Batch Directory, 3D, pool layout)", [
        sys.executable, os.path.join(REPO, "main.py"),
        "--output_dir", RUN3, "--continue_automatically", "true",
        "--b_input", RS_IMAGES, "--b_flight_log_path", MASTER_LOG,
        "--b_target_images", "7800", "--b_min_zone", "3000",
        "--b_max_zone", "8300", "--b_overlap_percent", "20",
        "--b_overlap_max_distance", "10", "--b_use_z", "true",
        "--b_xmp_priors", "false", "--b_zone_layout", "pool",
    ], os.path.join(LOGS, "zoning.log"),
        extra_env={"RS_MODULES": "Batch Directory"})


def stage_pair_repair():
    """Pool-aware pair repair: both eyes of a stereo pair belong in every
    zone either eye landed in (partner rows appended from the master log).
    Then enforce the <= ZONE_CAP owner invariant mechanically."""
    master = {}
    for ln in open(MASTER_LOG, encoding="utf-8").read().splitlines()[1:]:
        if ln:
            master[ln.split(";", 1)[0]] = ln
    hdr = open(MASTER_LOG, encoding="utf-8").readline().rstrip("\r\n")
    for zd in zone_dirs():
        zname = os.path.basename(zd)
        listfile = zone_list_of(zd)
        zlog = zone_log_of(zd)
        if not listfile or not zlog:
            abort(f"{zname}: missing imagelist or flight log")
        paths = [ln.strip() for ln in open(listfile, encoding="utf-8")
                 if ln.strip()]
        have = set(paths)
        added = 0
        for p in list(have):
            base = os.path.basename(p)
            if base.startswith("L_"):
                partner = os.path.join(RS_IMAGES, "R_" + base[2:])
            elif base.startswith("R_"):
                partner = os.path.join(RS_IMAGES, "L_" + base[2:])
            else:
                abort(f"{zname}: no eye token: {base}")
            if partner not in have and partner in master:
                have.add(partner)
                paths.append(partner)
                added += 1
        if len(paths) > ZONE_CAP:
            abort(f"{zname}: {len(paths)} images exceeds the owner cap "
                  f"{ZONE_CAP} after pair repair - re-zone with smaller "
                  "targets")
        if added:
            rows = [master[p] for p in paths if p in master]
            if len(rows) != len(paths):
                abort(f"{zname}: {len(paths) - len(rows)} paths have no "
                      "master-log row")
            with open(listfile + ".tmp", "w", encoding="utf-8",
                      newline="") as f:
                f.write("\r\n".join(paths) + "\r\n")
            os.replace(listfile + ".tmp", listfile)
            with open(zlog + ".tmp", "w", encoding="utf-8", newline="") as f:
                f.write(hdr + "\r\n" + "\r\n".join(rows) + "\r\n")
            os.replace(zlog + ".tmp", zlog)
        log(f"pair repair {zname}: {len(paths)} images "
            f"({added} partners added)")


# --------------------------------------------------------------- stage A

def caspar_window_check():
    """Prefer starting the first align after a CASPAR GPU-BA window
    clears (never kill; we outrank at NORMAL priority but avoid GPU
    contention at the start when cheap to do so)."""
    t0 = time.time()
    while time.time() - t0 < CASPAR_WAIT_CAP_S:
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-compute-apps=process_name",
                 "--format=csv,noheader"], capture_output=True, text=True,
                creationflags=NO_WINDOW, timeout=60).stdout.lower()
        except Exception as exc:
            log(f"nvidia-smi check failed ({exc}) - proceeding")
            return
        if "colmap" not in out:
            log("GPU compute check: no colmap.exe in compute apps - clear")
            return
        log("GPU compute check: colmap.exe holds a GPU (CASPAR arm?) - "
            "waiting 10 min (cap 4 h; will proceed at cap)")
        time.sleep(600)
    log("CASPAR wait cap reached - proceeding at NORMAL priority")


def zone_fingerprint(zone_log):
    return align_fingerprint.build_fingerprint(
        zone_log, LOCAL_TEMPLATE, ALIGN_PARAMS, MIN_COMPONENT,
        rs_executable=RS_EXE)


def zone_baseline(zone_out_dir):
    """(median solved L-R baseline, n_pairs) across every identity_r*
    harvest of a zone - the census channel is the only pose oracle."""
    pos = {}
    for f in glob.glob(os.path.join(zone_out_dir, "identity_r*", "*.xmp")):
        t = open(f, encoding="utf-8", errors="replace").read()
        m = re.search(r"<xcr:Position>([^<]+)</xcr:Position>|"
                      r'xcr:Position="([^"]+)"', t)
        if m:
            pos[os.path.splitext(os.path.basename(f))[0]] = [
                float(v) for v in (m.group(1) or m.group(2)).split()]
    baselines = []
    for k, a in pos.items():
        if not k.startswith("L_"):
            continue
        b = pos.get("R_" + k[2:])
        if b:
            baselines.append(sum((x - y) ** 2
                                 for x, y in zip(a, b)) ** 0.5)
    baselines.sort()
    if not baselines:
        return None, 0
    return baselines[len(baselines) // 2], len(baselines)


def stage_aligns(arm):
    first = True
    for zd in zone_dirs():
        zname = os.path.basename(zd)
        zlog = zone_log_of(zd)
        listfile = zone_list_of(zd)
        out_zone = os.path.join(COMPONENTS, zname)
        fp = zone_fingerprint(zlog)
        if (glob.glob(os.path.join(out_zone, "*.rsalign"))
                and align_fingerprint.matches_current(out_zone, fp)):
            log(f"=== align {zname} SKIPPED (fingerprint match)")
            continue
        if first:
            caspar_window_check()
            first = False
        guard_disk()
        limit, used = commit_state_gb()
        if limit - used < COMMIT_HEADROOM_GB:
            abort(f"commit headroom {limit - used:.0f} GB below "
                  f"{COMMIT_HEADROOM_GB} GB before align {zname}")
        members = [ln.strip() for ln in open(listfile, encoding="utf-8")
                   if ln.strip()]
        rscmd = build_rscmd(zname, members, arm)
        purge_pool_pose_xmps()
        clear_markers()
        run_cmd(f"align {zname} ({len(members)} images)", [
            sys.executable, os.path.join(REPO, "main.py"),
            "--output_dir", RUN3, "--continue_automatically", "true",
            "--r_input", zd, "--r_flight_log", zlog,
            "--r_min_component_size", str(MIN_COMPONENT),
            "--r_project_label", "", "--r_model_generate", "false",
            "--r_model_cull_poly", "false", "--r_model_texture", "false",
            "--r_model_simplify", "false", "--r_display_output", "false",
        ], os.path.join(LOGS, f"align_{zname}.log"),
            extra_env=dict(ALIGN_ENV, RS_CALIB_XMP_RSCMD=rscmd))
        # ZONE-SCALE metric invariant: solved rig baseline from the
        # identity harvest must sit within 1.5% of the 0.16970 m oracle.
        # This is the scale check at the scale where 0.5 m priors
        # actually constrain the solve (a 30-pair fixture cannot -
        # measured drift there; see fixture_cells evidence 2026-08-28).
        med, npairs = zone_baseline(os.path.join(COMPONENTS, zname))
        if med is None or npairs < 50:
            abort(f"align {zname}: no measurable rig baseline "
                  f"({npairs} pairs) - cannot certify metric scale")
        dev = (med - BASELINE_ORACLE) / BASELINE_ORACLE
        log(f"align {zname}: solved baseline {med:.5f} m "
            f"({dev*100:+.2f}%, {npairs} pairs)")
        if abs(dev) > 0.015:
            abort(f"align {zname}: solved baseline {med:.5f} m off the "
                  f"metric oracle by {dev*100:+.2f}% (>1.5%) - metric "
                  "invariant violated; stopping (C-20260730-05 recipe "
                  "held 0.24% at cm priors; investigate before merging)")


# --------------------------------------------------------------- stage G

def stage_grow():
    for zd in zone_dirs():
        zname = os.path.basename(zd)
        gout = os.path.join(GROWN, zname)
        report = os.path.join(gout, "grow_report.json")
        if os.path.isfile(report):
            log(f"=== grow {zname} SKIPPED (report exists)")
            continue
        scene = os.path.join(COMPONENTS, zname, f"{zname}.rsproj")
        if not os.path.isfile(scene):
            abort(f"grow {zname}: scene missing: {scene}")
        guard_disk()
        purge_pool_pose_xmps()
        clear_markers()
        run_cmd(f"grow {zname}", [
            sys.executable, os.path.join(REPO, "grow_zone.py"),
            "--scene", scene, "--images_root", RS_IMAGES,
            "--zone_imagelist", zone_list_of(zd),
            "--components_dir", os.path.join(COMPONENTS, zname),
            "--output", gout, "--min_size", str(MIN_COMPONENT),
            "--max_passes", "4", "--flight_log", zone_log_of(zd),
            "--flight_log_params", LOCAL_TEMPLATE,
            "--project_label", "",
        ], os.path.join(LOGS, f"grow_{zname}.log"))


# --------------------------------------------------------------- stage M

def load_zone_components():
    """zone -> [(rsalign, camera_count, member_basenames)] from grow's
    final complists (authoritative export paths + manifests)."""
    zones = {}
    for zd in zone_dirs():
        zname = os.path.basename(zd)
        comps = []
        complist = os.path.join(GROWN, zname, "final.complist")
        entries = []
        if os.path.isfile(complist):
            entries = [ln.strip() for ln in open(complist, encoding="utf-8")
                       if ln.strip()]
        if not entries:
            # grow accepted nothing / bootstrap: fall back to the align
            # exports
            entries = sorted(glob.glob(os.path.join(COMPONENTS, zname,
                                                    "*.rsalign")))
            log(f"WARNING: {zname}: using align-stage exports "
                f"({len(entries)}) - no grow final.complist")
        for rsalign in entries:
            mpath = rsalign + ".manifest.json"
            if not os.path.isfile(mpath):
                log(f"WARNING: {zname}: no manifest for {rsalign} - "
                    "component excluded from the merge plan")
                continue
            m = json.load(open(mpath, encoding="utf-8"))
            members = {os.path.basename(i).lower()
                       for i in (m.get("images") or [])}
            comps.append((rsalign, m.get("camera_count") or len(members),
                          members))
        zones[zname] = comps
    return zones


def plan_groups(zones):
    """Adjacency-greedy grouping under the 34k ceiling (C-20260802-01):
    primary = maximal union reachable from the largest zone via shared
    cameras; remainder = the rest (must also fit the ceiling)."""
    zmembers = {z: set().union(*[c[2] for c in comps]) if comps else set()
                for z, comps in zones.items()}
    remaining = {z for z, m in zmembers.items() if m}
    groups = []
    while remaining:
        seed = max(remaining, key=lambda z: len(zmembers[z]))
        group = [seed]
        union = set(zmembers[seed])
        remaining.discard(seed)
        while True:
            best, best_shared = None, 0
            for z in remaining:
                shared = len(zmembers[z] & union)
                if shared > best_shared and \
                        len(union | zmembers[z]) <= CEILING:
                    best, best_shared = z, shared
            if best is None:
                break
            group.append(best)
            union |= zmembers[best]
            remaining.discard(best)
        groups.append({"zones": group, "unique_cameras": len(union)})
    return groups


def stage_merges():
    zones = load_zone_components()
    empty = [z for z, comps in zones.items() if not comps]
    if empty:
        abort(f"stage M: zone(s) with ZERO manifested components: {empty} "
              "- a silent drop here would deliver a partial survey "
              "(C-20260827-06 class); investigate before merging")
    total_unique = len(set().union(*[c[2] for comps in zones.values()
                                     for c in comps])) if zones else 0
    groups = plan_groups(zones)
    plan = {"total_unique_cameras": total_unique, "ceiling": CEILING,
            "groups": groups}
    json.dump(plan, open(os.path.join(AGENT, "merge_plan.json"), "w",
                         encoding="utf-8"), indent=2)
    log(f"merge plan: {json.dumps(plan)}")
    if total_unique > CEILING:
        log(f"NOTE: full unification ({total_unique:,}) exceeds the "
            f"{CEILING:,} ceiling (C-20260802-01) - delivering "
            f"{len(groups)} unified group(s); NO full-survey merge scene")
    results = {}
    for gi, group in enumerate(groups):
        gname = "primary" if gi == 0 else f"remainder_{gi}"
        fdir = os.path.join(MERGED, gname)
        report = os.path.join(fdir, "merge_report.json")
        entries = [c[0] for z in group["zones"] for c in zones[z]]
        if len(entries) == 1:
            results[gname] = {"mode": "single-component",
                              "rsalign": entries[0],
                              "zones": group["zones"]}
            log(f"=== merge {gname} SKIPPED (single component)")
            continue
        if os.path.isfile(report):
            log(f"=== merge {gname} SKIPPED (report exists)")
            results[gname] = {"mode": "merged", "report": report,
                              "zones": group["zones"]}
            continue
        guard_disk()
        limit, used = commit_state_gb()
        need = 262.0 * group["unique_cameras"] / 34_000 + 40.0
        if limit - used < need:
            abort(f"merge {gname}: commit headroom {limit - used:.0f} GB "
                  f"< projected {need:.0f} GB")
        os.makedirs(fdir, exist_ok=True)
        complist = os.path.join(fdir, f"{gname}.complist")
        with open(complist, "w", encoding="utf-8", newline="\r\n") as f:
            f.write("\n".join(entries) + "\n")
        purge_pool_pose_xmps()
        clear_markers()
        run_cmd(f"merge {gname} ({group['unique_cameras']:,} unique)", [
            sys.executable, os.path.join(REPO, "merge_zones.py"),
            "--components_root", GROWN, "--images_root", ZONES,
            "--output", fdir, "--name", f"{CODE}_{gname}",
            "--complist", complist,
            "--ladder", "merge_first", "--merge_scope", "neighbour",
            "--pair_gate", "overlap", "--loss_tolerance", LOSS_TOLERANCE,
            "--min_size", str(MERGE_MIN_SIZE),
            "--max_scene_cameras", str(CEILING),
            "--auto_model", "false", "--assemble_only", "false",
            "--scale_gate", "true", "--scale_min", "0.9",
            "--scale_max", "1.1", "--visible", "false",
            "--target", "0.9", "--project_label", "",
        ], os.path.join(LOGS, f"merge_{gname}.log"))
        results[gname] = {"mode": "merged", "report": report,
                          "zones": group["zones"]}
    return plan, results


# --------------------------------------------------------------- stage X

def sha16(path):
    return (align_fingerprint.sha256_file(path) or "")[:16]


def stage_manifest(plan, merge_results):
    manifest = {
        "schema": 0,
        "campaign": CODE,
        "created": f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}",
        "coordinate_frame": {
            "name": "local:1 Euclidean, gravity Z-up, TRUE-NORTH +Y, "
                    "metric scale 1.0",
            "absolute_georeference":
                "NONE - UTM BLOCKED: nav fit failed gates (USBL median "
                "residual 4.9 m vs 0.5 m gate; per-dive scales 0.94/0.83; "
                "see nav/nav_fit.json). Approximate UTM17T "
                "translation-level georef recorded in "
                "nav/frame_of_record.json for the FINAL cloud only.",
            "utm_zone_answer": "17T (EPSG:32617) from actual nav "
                               "longitude median -78.5607",
            "nav_source": "COLMAP sparse/0 (M:/ON2026_colmap2) - metric "
                          "via rig baseline 0.16970 m exact",
            "master_log": MASTER_LOG,
            "master_log_sha256_16": sha16(MASTER_LOG),
            "frame_of_record": os.path.join(RUN3, "nav",
                                            "frame_of_record.json"),
        },
        "settings": {
            "alignment_params": ALIGN_PARAMS,
            "alignment_sha256_16": sha16(ALIGN_PARAMS),
            "distortion": "Brown3 (owner order; C-20260730-09 measured "
                          "Division better on this imagery - recorded)",
            "features_per_image": 20000, "sensitivity": "High",
            "pos_accuracy_m": 0.5, "ori_accuracy_floor_deg": 10,
            "calibration": {
                "arm": calib_arm(),
                "channel": "-addImageWithCalibration per-image XMPs "
                           "(validated; setPriorCalibrationGroup does "
                           "not stick from CLI)",
                "groups": "per-eye L=0 R=1 delivered; RS merges to one "
                          "group (groups arm) or per-image -1 (values "
                          "arm) - per-eye ids do not survive",
                "values": "COLMAP-solved PINHOLE (identical to "
                          "manufacturer resized-corrected)",
                "focal_px": INTRINSICS[0][0],
            },
            "min_component_size": MIN_COMPONENT,
            "merge": {"ladder": "merge_first",
                      "loss_tolerance": LOSS_TOLERANCE,
                      "ceiling": CEILING},
        },
        "fixture_verdict": os.path.join(AGENT, "fixture_verdict.json"),
        "merge_plan": plan,
        "groups": {},
    }
    for gname, res in merge_results.items():
        rsaligns = []
        if res["mode"] == "merged":
            fdir = os.path.join(MERGED, gname)
            rsaligns = sorted(glob.glob(os.path.join(fdir, "**",
                                                     "*.rsalign"),
                                        recursive=True),
                              key=os.path.getmtime)
        else:
            rsaligns = [res["rsalign"]]
        manifest["groups"][gname] = {
            "zones": res["zones"], "mode": res["mode"],
            "components": [{"path": p, "bytes": os.path.getsize(p)}
                           for p in rsaligns if os.path.isfile(p)],
        }
    path = os.path.join(RUN3, "DELIVERABLE_MANIFEST.json")
    json.dump(manifest, open(path, "w", encoding="utf-8"), indent=2)
    log(f"manifest written: {path}")


def main():
    # schtasks-launched trees default to BELOW-NORMAL priority; the owner
    # directive puts run3's RS work at NORMAL (outranks the GPU-BA test
    # arms, which run below-normal by their own design). Children inherit.
    ctypes.windll.kernel32.SetPriorityClass(
        ctypes.windll.kernel32.GetCurrentProcess(), 0x00000020)
    for d in (LOGS, AGENT, COMPONENTS, GROWN, MERGED, CONFIG, RSCMD_DIR):
        os.makedirs(d, exist_ok=True)
    arm = calib_arm()
    log(f"driver start: {CODE} run3 from {RUN3} (owner-directed, "
        f"fully autonomous; calibration arm={arm})")
    stage_preflight()
    guard_campaign_arm(arm)
    stage_calibration_inputs(arm)
    stage_fixture(arm)
    stage_zoning()
    stage_pair_repair()
    stage_aligns(arm)
    stage_grow()
    plan, merges = stage_merges()
    stage_manifest(plan, merges)
    log("driver DONE")


if __name__ == "__main__":
    main()
