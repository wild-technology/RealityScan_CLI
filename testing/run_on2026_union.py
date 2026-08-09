r"""ON2026 union wave: merge the masts into the hull -> ONE wreck scene
-> model (owner directive 2026-08-09: "After hull merge, we need to
also merge the masts into it. Take this to completion.").

Launched AFTER run2's driver finishes (or after its hull merge fails -
see path pick). Own log: M:\ON2026_run2\logs\union.log. Chain:

  P  path pick by MEASURED commit limit (GlobalMemoryStatusEx):
       direct - limit >= DIRECT_MIN_COMMIT: union the EXISTING merged
                components (hull + mast_a + mast_b = 45,362 slots,
                projected ~328 GB commit; only possible after the owner
                raises the pagefile - informed 2026-08-09)
       pool   - otherwise: pool-layout wave. Zone MEMBERSHIP is taken
                from the EXISTING pair-repaired zone logs (identical to
                the validated aligns - no re-zoning drift): each zone
                becomes an .imagelist of canonical pool paths + a
                full-path flight log; aligns run with RS_ALIGN_POOL_DIR
                so overlap images are SHARED cameras; the union scene
                is 37,363 unique cameras (~281 GB projected, fits the
                319.5 GB limit). Also the fallback if the copy-layout
                hull merge OOMs - the pool union IS hull+masts.
  A  (pool only) per-zone pool aligns, fingerprint-resumable
  M  union merge (merge_zones.py, every argument explicit)
  D  ComputeModel -> finish_model on the union scene (4x8k objmetric)
  X  UNION_MANIFEST.json

Envelope numbers: C-20260802-01 two-point line commit(N) ~= 262 GB +
(N-34,105)*5.9 MB. 45,362 -> ~328 GB; 37,363 -> ~281 GB.
"""
from __future__ import annotations

import ctypes
import datetime
import glob
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN2 = r"M:\ON2026_run2"
CODE = "ON2026_RH0041_RH2042"
NAV = os.path.join(RUN2, "nav", "flight_log_run2.txt")
POOL_IMAGES = os.path.join(RUN2, "rs_images")
ZONES = os.path.join(RUN2, "batched_images_by_zone")
COMPONENTS = os.path.join(RUN2, "aligned_components")
MERGED = os.path.join(RUN2, "features")
MODELS = os.path.join(RUN2, "models")
LOGS = os.path.join(RUN2, "logs")
AGENT = os.path.join(RUN2, "_agent")
POOL = os.path.join(RUN2, "pool")
POOL_ZONES = os.path.join(POOL, "zones")
POOL_COMPONENTS = os.path.join(POOL, "aligned_components")
DRIVER_LOG = os.path.join(LOGS, "union.log")
CONFIG = os.path.join(RUN2, "config")
ALIGN_PARAMS = os.path.join(CONFIG, "ON2026_AlignmentParams.xml")
SCRIPTS = os.path.join(REPO, "modules", "realityscan_interface", "RS_CLI",
                       "Scripts")
ERRORS_DIR = os.path.join(REPO, "modules", "realityscan_interface", "RS_CLI",
                          "Errors")

MIN_COMPONENT = 10
MERGE_MIN_SIZE = 10
LOSS_TOLERANCE = "0.015"
MIN_FREE_GB = 150.0
NO_WINDOW = 0x08000000

# Path thresholds/ceilings (GB / cameras), all from the measured
# envelope; see module docstring.
DIRECT_MIN_COMMIT_GB = 380.0     # 328 projected + baseline headroom
DIRECT_CEILING = 46_000
POOL_CEILING = 38_000            # 37,363 unique + margin; ~281 GB proj.

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


def clear_markers():
    for n in ("errors_RS1.txt", "results_RS1.log"):
        p = os.path.join(ERRORS_DIR, n)
        if os.path.isfile(p):
            os.remove(p)


def guard_disk():
    if shutil.disk_usage(RUN2).free / 1e9 < MIN_FREE_GB:
        abort(f"M: free space below {MIN_FREE_GB} GB")


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


def commit_limit_gb() -> float:
    """The REAL commit ceiling (RAM + pagefile), measured not assumed."""
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
    return st.ullTotalPageFile / 1e9


# ------------------------------------------------------------ direct path

def existing_union_inputs():
    """(complist entries, total slots) for the direct union - the three
    per-feature results of the copy-layout run. None if any is missing."""
    plan_path = os.path.join(AGENT, "features_plan.json")
    if not os.path.isfile(plan_path):
        return None, 0
    plans = json.load(open(plan_path, encoding="utf-8"))
    entries, total = [], 0
    # mast_a: single component straight from its zone
    for feat in ("mast_a", "mast_b", "hull"):
        plan = plans.get(feat)
        if not plan:
            return None, 0
        total += plan["total_cameras"]
        if len(plan["components"]) == 1:
            entries.append(plan["components"][0]["rsalign"])
            continue
        fdir = os.path.join(MERGED, feat)
        if not os.path.isfile(os.path.join(fdir, "merge_report.json")):
            return None, 0
        merged = sorted(glob.glob(os.path.join(fdir, "**", "*.rsalign"),
                                  recursive=True), key=os.path.getmtime)
        if not merged:
            return None, 0
        entries.append(merged[-1])
    return entries, total


# -------------------------------------------------------------- pool path

def build_pool_zones():
    """Pool zones from the EXISTING pair-repaired zone logs: identical
    membership to the validated aligns, rows rewritten to canonical
    pool paths, plus per-zone .imagelist. Idempotent."""
    os.makedirs(POOL_ZONES, exist_ok=True)
    built = 0
    for zdir in sorted(glob.glob(os.path.join(ZONES, "zone_*"))):
        zname = os.path.basename(zdir)
        logs = glob.glob(os.path.join(zdir, "flight_log*_UTM.txt"))
        if len(logs) != 1:
            abort(f"{zname}: expected exactly one zone log, found {logs}")
        pzdir = os.path.join(POOL_ZONES, zname)
        os.makedirs(pzdir, exist_ok=True)
        out_log = os.path.join(pzdir, "flight_log_UTM.txt")
        out_list = os.path.join(pzdir, f"{zname}.imagelist")
        if os.path.isfile(out_log) and os.path.isfile(out_list):
            continue
        rows, paths, missing = [], [], 0
        for ln in open(logs[0], encoding="utf-8"):
            ln = ln.rstrip("\r\n")
            if not ln or ln.startswith("filename"):
                continue
            parts = ln.split(";")
            pool_path = os.path.join(POOL_IMAGES, os.path.basename(parts[0]))
            if not os.path.isfile(pool_path):
                missing += 1
                continue
            parts[0] = pool_path
            rows.append(";".join(parts))
            paths.append(pool_path)
        if missing:
            log(f"WARNING: {zname}: {missing} zone-log row(s) have no pool "
                "file - dropped (err:18002 guard)")
        if not rows:
            abort(f"{zname}: zero pool rows")
        hdr = open(logs[0], encoding="utf-8").readline().rstrip("\r\n")
        with open(out_log, "w", encoding="utf-8", newline="") as f:
            f.write(hdr + "\r\n" + "\r\n".join(rows) + "\r\n")
        with open(out_list, "w", encoding="utf-8", newline="") as f:
            f.write("\r\n".join(paths) + "\r\n")
        built += 1
        log(f"pool zone {zname}: {len(rows)} full-path rows")
    if built:
        log(f"pool zones built/refreshed: {built}")


def pool_align_zones():
    for pzdir in sorted(glob.glob(os.path.join(POOL_ZONES, "zone_*")),
                        key=lambda d: int(d.rsplit("_", 1)[1])):
        zname = os.path.basename(pzdir)
        zout = os.path.join(POOL_COMPONENTS, zname)
        if glob.glob(os.path.join(zout, "*.manifest.json")):
            log(f"=== pool align {zname} SKIPPED (manifests exist)")
            continue
        guard_disk()
        clear_markers()
        run_cmd(f"pool align {zname}", [
            sys.executable, os.path.join(REPO, "main.py"),
            "--output_dir", POOL, "--continue_automatically", "true",
            "--r_input", pzdir,
            "--r_flight_log", os.path.join(pzdir, "flight_log_UTM.txt"),
            "--r_min_component_size", str(MIN_COMPONENT),
            "--r_project_label", "", "--r_model_generate", "false",
            "--r_model_cull_poly", "false", "--r_model_texture", "false",
            "--r_model_simplify", "false", "--r_display_output", "false",
        ], os.path.join(LOGS, f"pool_align_{zname}.log"),
            extra_env={"RS_MODULES": "RealityScan Alignment",
                       "RS_ALIGN_POOL_DIR": POOL_IMAGES})


def pool_union_inputs():
    entries = sorted(glob.glob(os.path.join(POOL_COMPONENTS, "*",
                                            "*.rsalign")))
    total = 0
    for mp in glob.glob(os.path.join(POOL_COMPONENTS, "*",
                                     "*.manifest.json")):
        total += json.load(open(mp, encoding="utf-8")).get(
            "camera_count") or 0
    return entries, total


# ------------------------------------------------------------------ merge

def union_merge(entries, ceiling, images_root, comp_root, tag):
    fdir = os.path.join(MERGED, "wreck")
    name = f"{CODE}_wreck"
    report = os.path.join(fdir, "merge_report.json")
    if os.path.isfile(report):
        log(f"=== union merge SKIPPED (report exists)")
        return fdir
    guard_disk()
    os.makedirs(fdir, exist_ok=True)
    complist = os.path.join(fdir, "wreck.complist")
    with open(complist, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(entries) + "\n")
    clear_markers()
    run_cmd(f"union merge ({tag})", [
        sys.executable, os.path.join(REPO, "merge_zones.py"),
        "--components_root", comp_root, "--images_root", images_root,
        "--output", fdir, "--name", name, "--complist", complist,
        "--ladder", "merge_first", "--merge_scope", "neighbour",
        "--pair_gate", "overlap", "--loss_tolerance", LOSS_TOLERANCE,
        "--min_size", str(MERGE_MIN_SIZE),
        "--max_scene_cameras", str(ceiling),
        "--auto_model", "false", "--assemble_only", "false",
        "--scale_gate", "true", "--scale_min", "0.9",
        "--scale_max", "1.1", "--visible", "false",
        "--target", "0.9", "--project_label", "",
    ], os.path.join(LOGS, "merge_wreck.log"))
    return fdir


# ------------------------------------------------------------------ model

def union_model(fdir):
    outdir = os.path.join(MODELS, "wreck")
    final_name = f"{CODE}_wreck"
    if glob.glob(os.path.join(outdir, final_name + "*.obj")):
        log("=== union model SKIPPED (deliverable exists)")
        return
    scenes = sorted(glob.glob(os.path.join(fdir, "**", "*.rsproj"),
                              recursive=True), key=os.path.getmtime)
    if not scenes:
        abort("no union scene found for the model stage")
    scene = scenes[-1]
    guard_disk()
    os.makedirs(outdir, exist_ok=True)
    model_name = f"{final_name}_HighPoly"
    clear_markers()
    run_cmd("mesh wreck", [
        os.path.join(SCRIPTS, "ComputeModel.bat"),
        scene, "", model_name,
    ], os.path.join(LOGS, "mesh_wreck.log"))
    run_cmd("finish wreck", [
        sys.executable, os.path.join(REPO, "finish_model.py"),
        "--instance", "RS1", "--outdir", outdir, "--name", final_name,
        "--preset", "4x8k", "--simplify", "true",
        "--format", "objmetric", "--source-model", model_name,
        "--save-path", scene,
    ], os.path.join(LOGS, "finish_wreck.log"))
    subprocess.run([os.path.join("C:\\", "Program Files", "Epic Games",
                                 "RealityScan_2.2", "RealityScan.exe"),
                    "-delegateTo", "RS1", "-quit"],
                   creationflags=NO_WINDOW)
    time.sleep(10)


def main():
    for d in (LOGS, AGENT, MERGED, MODELS):
        os.makedirs(d, exist_ok=True)
    log(f"union driver start: {CODE} (owner directive 2026-08-09: "
        "hull+masts -> one wreck deliverable)")
    guard_disk()
    limit = commit_limit_gb()
    entries, slots = existing_union_inputs()
    log(f"commit limit {limit:.1f} GB; direct-union inputs "
        f"{'READY (%d slots)' % slots if entries else 'not available'}")
    if entries and limit >= DIRECT_MIN_COMMIT_GB:
        log(f"path: DIRECT union ({slots:,} slots, ceiling "
            f"{DIRECT_CEILING:,}, projected ~328 GB <= {limit:.0f} GB)")
        fdir = union_merge(entries, DIRECT_CEILING, ZONES, COMPONENTS,
                           "direct")
    else:
        why = ("commit limit too low for 45,362 slots"
               if entries else "copy-layout union inputs incomplete")
        log(f"path: POOL wave ({why}); union at ~37,363 unique cameras")
        build_pool_zones()
        pool_align_zones()
        entries, total = pool_union_inputs()
        if not entries:
            abort("pool wave produced no components")
        log(f"pool components: {len(entries)}, {total:,} cameras")
        if total > POOL_CEILING:
            abort(f"pool union {total:,} exceeds {POOL_CEILING:,} - "
                  "re-measure the envelope before proceeding")
        fdir = union_merge(entries, POOL_CEILING, POOL_ZONES,
                           POOL_COMPONENTS, "pool")
    union_model(fdir)
    manifest = {
        "schema": 0, "campaign": CODE,
        "created": f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}",
        "deliverable": "wreck (hull + mast_a + mast_b unified)",
        "commit_limit_gb": limit,
        "deliverables": [{"path": p, "bytes": os.path.getsize(p)}
                         for p in sorted(glob.glob(
                             os.path.join(MODELS, "wreck", "*.obj")))],
    }
    path = os.path.join(MODELS, "UNION_MANIFEST.json")
    json.dump(manifest, open(path, "w", encoding="utf-8"), indent=2)
    log(f"union manifest written: {path}")
    log("union driver DONE")


if __name__ == "__main__":
    main()
