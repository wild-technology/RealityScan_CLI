r"""Overnight workbench seed-growth campaign (owner directive 2026-08-11).

Drives the LIVE GUI instance RSGUI (owner's workbench scene) via the
attach-only NightGrow.bat primitives - never boots, never -newScene,
never -quit; the GUI stays active all night. Log:
M:\ON2026_run2\logs\night.log; workdir M:\ON2026_run2\_agent\night.

Owner's plan, implemented stage by stage:
  W  wait for the owner's in-flight alignment to finish (progress file
     goes stale/completed AND the instance answers idle)
  C0 hourly-save loop armed; checkpoint bundle; census #0
     (save -> in-memory peel -> reload; probe-validated non-destructive)
  D  delete the SECOND-LARGEST component (checkpoint first)
  O  orphan breakout: pool basenames minus registered; yellow-tether
     screen (tether-strict HSV profile; calibration 2026-08-11 showed
     naive yellow culls quagga-mussel wreck detail - strict profile
     only, plus a 20% sanity cap; NOTHING is deleted from disk, the
     screen only excludes from the ADD list; flagged list saved for
     morning review)
  A  add accepted orphans + flight-log priors; added images set to
     ALL FEATURES (aligFeaturesMode=2) per owner - registered images
     keep their existing feature source
  S  seed-growth passes: disable ALL, enable ONLY small components +
     orphans (largest component stays disabled, per owner), align,
     census, never-shrink verdict (accept iff no previously-registered
     basename lost AND count >= before; else scene_checkpoint restore).
     Loop until a pass registers nothing new (converged), pass cap, or
     two consecutive rollbacks (storm -> stop and report).
  M  only then: enable ALL and attempt largest+rest merging - rigid
     -mergeComponents first (free consolidation, cannot shrink), then
     ONE align rung if still split, each under checkpoint + census.
  R  final save + NIGHT_REPORT.json.
"""
from __future__ import annotations

import datetime
import glob
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module_base import scene_checkpoint  # noqa: E402
from modules.realityscan_interface.realityscan_cli import RealityScanCLI  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN2 = r"M:\ON2026_run2"
SCENE = os.path.join(RUN2, "workbench", "ON2026_RH0041_RH2042_workbench.rsproj")
POOL = os.path.join(RUN2, "rs_images")
ZONES = os.path.join(RUN2, "batched_images_by_zone")
NAV = os.path.join(RUN2, "nav", "flight_log_run2.txt")
FLPARAMS = os.path.join(RUN2, "config", "FlightLogParamsLocal.xml")
ALIGN_PARAMS = os.path.join(RUN2, "config", "ON2026_AlignmentParams.xml")
WORK = os.path.join(RUN2, "_agent", "night")
CKPTS = os.path.join(WORK, "checkpoints")
LOGS = os.path.join(RUN2, "logs")
NIGHT_LOG = os.path.join(LOGS, "night.log")
ERRORS_DIR = os.path.join(REPO, "modules", "realityscan_interface", "RS_CLI",
                          "Errors")
ERRORS_FILE = os.path.join(ERRORS_DIR, "errors_RSGUI.txt")
PROGRESS_FILE = os.path.join(ERRORS_DIR, "progress_RSGUI.txt")
YELLOW = os.path.join(REPO, "testing", "yellow_filter.py")
INSTANCE = "RSGUI"

MAX_SEED_PASSES = 6
ROLLBACK_STORM = 2
YELLOW_THRESHOLD = 0.01          # tether-strict profile (calibration 2026-08-11)
YELLOW_CAP_FRACTION = 0.20       # if >20% of orphans flag, distrust the screen
SAVE_INTERVAL_S = 3600
MIN_FREE_GB = 150.0

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("night")


def log(msg):
    line = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} | {msg}"
    print(line, flush=True)
    os.makedirs(LOGS, exist_ok=True)
    with open(NIGHT_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def abort(msg):
    log(f"ABORT: {msg}")
    sys.exit(1)


def clear_errors():
    if os.path.isfile(ERRORS_FILE):
        os.remove(ERRORS_FILE)


class _Settings:
    """Minimal settings shim for RealityScanCLI (no store needed)."""

    def get(self, _section, _key, fallback=None):
        return fallback

    def set(self, *_a, **_k):
        pass


CLI = RealityScanCLI(logger, _Settings())


def night(mode, *args):
    """One NightGrow.bat primitive against the live instance."""
    clear_errors()
    t0 = time.time()
    result = CLI.run_attach_script("NightGrow.bat", [mode, *args],
                                   LOGS, instance=INSTANCE)
    mins = (time.time() - t0) / 60
    if not result.success:
        log(f"NightGrow {mode} FAILED after {mins:.1f} min: "
            f"{result.errors or result.return_code} (log: {result.log_path})")
        return False
    log(f"NightGrow {mode} ok ({mins:.1f} min)")
    return True


# ------------------------------------------------------------------ wait

def owner_align_idle(stale_minutes=12):
    """True when the owner's alignment is done: progress file stale or
    terminal, and no fresh #progress lines."""
    try:
        mtime = os.path.getmtime(PROGRESS_FILE)
    except OSError:
        return True
    age_min = (time.time() - mtime) / 60
    if age_min < stale_minutes:
        try:
            tail = open(PROGRESS_FILE, encoding="utf-8",
                        errors="replace").read().splitlines()[-1]
        except (OSError, IndexError):
            return False
        if "#progress" in tail:
            return False
    return True


def stage_wait():
    log("W: waiting for the owner's alignment to go idle "
        "(progress stale >12 min)")
    while not owner_align_idle():
        time.sleep(120)
    log("W: instance idle - campaign starting")


# ---------------------------------------------------------------- census

def census(tag):
    """Non-destructive component census. Returns (components, registered):
    components = [(name, count, stems_set)] largest first."""
    outdir = os.path.join(WORK, f"census_{tag}")
    if os.path.isdir(outdir):
        shutil.rmtree(outdir)
    os.makedirs(outdir)
    if not night("census", SCENE, outdir, ZONES, POOL):
        return None, None
    rounds = []
    for rdir in sorted(glob.glob(os.path.join(outdir, "census_r*")),
                       key=lambda d: int(d.rsplit("r", 1)[1])):
        stems = {os.path.splitext(f)[0].lower()
                 for f in os.listdir(rdir) if f.lower().endswith(".xmp")}
        rounds.append(stems)
    comps = []
    rsaligns = sorted(glob.glob(os.path.join(outdir, "*.rsalign")),
                      key=os.path.getmtime)
    for i in range(len(rounds)):
        later = rounds[i + 1] if i + 1 < len(rounds) else set()
        members = rounds[i] - later
        name = (os.path.basename(rsaligns[i])[:-len(".rsalign")]
                if i < len(rsaligns) else f"component_{i}")
        comps.append((name, len(members), members))
    comps.sort(key=lambda c: -c[1])
    registered = set().union(*rounds) if rounds else set()
    log(f"census {tag}: {len(comps)} component(s): "
        + ", ".join(f"{n}={c:,}" for n, c, _ in comps[:8])
        + f"; registered {len(registered):,}")
    with open(os.path.join(WORK, f"census_{tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump([{"name": n, "count": c} for n, c, _ in comps], f, indent=2)
    return comps, registered


# ------------------------------------------------------------- utilities

def pool_index():
    idx = {}
    for f in os.listdir(POOL):
        if f.lower().endswith(".jpg"):
            idx[os.path.splitext(f)[0].lower()] = os.path.join(POOL, f)
    return idx


def write_list(path, paths):
    with open(path, "w", encoding="ascii", newline="") as f:
        f.write("\r\n".join(paths) + "\r\n")
    return path


def checkpoint(tag):
    return scene_checkpoint.checkpoint_scene(SCENE, CKPTS, tag, logger)


def restore(tag):
    """Roll the on-disk bundle back to a checkpoint, then LOAD it into
    the live instance. Never save first - the in-memory state is the
    rejected one; saving it would overwrite the bundle being restored."""
    scene_checkpoint.restore_scene(SCENE, CKPTS, tag, logger)
    subprocess.run([CLI.find_executable(), "-delegateTo", INSTANCE,
                    "-load", SCENE], creationflags=0x08000000)
    time.sleep(8)
    subprocess.run([CLI.find_executable(), "-waitCompleted", INSTANCE],
                   creationflags=0x08000000)
    subprocess.run([CLI.find_executable(), "-waitCompleted", INSTANCE],
                   creationflags=0x08000000)


def hourly_saver(stop_event):
    while not stop_event.wait(SAVE_INTERVAL_S):
        log("hourly save")
        night("saveonly", SCENE)


# ------------------------------------------------------------------ main

def main():
    for d in (WORK, CKPTS, LOGS):
        os.makedirs(d, exist_ok=True)
    if not os.path.isfile(SCENE):
        abort(f"workbench scene not found: {SCENE}")
    if shutil.disk_usage(RUN2).free / 1e9 < MIN_FREE_GB:
        abort("insufficient free disk")
    log("night campaign start (attach-only, GUI stays active)")

    stage_wait()

    stop = threading.Event()
    saver = threading.Thread(target=hourly_saver, args=(stop,), daemon=True)

    # C0: checkpoint + census
    checkpoint("night_c0")
    comps, registered = census("c0")
    if comps is None:
        abort("census #0 failed")
    saver.start()

    # D: delete the second-largest component (owner instruction)
    if len(comps) >= 2:
        second = comps[1]
        log(f"D: deleting second-largest component {second[0]} "
            f"({second[1]:,} cams) per owner instruction")
        checkpoint("night_pre_delete")
        if not night("delete2nd", SCENE, second[0]):
            abort("delete2nd failed - scene checkpointed at night_pre_delete")
        comps, registered = census("post_delete")
        if comps is None:
            abort("post-delete census failed")
    else:
        log("D: fewer than 2 components - nothing to delete")

    # O: orphan breakout + yellow screen
    idx = pool_index()
    orphan_stems = sorted(set(idx) - registered)
    log(f"O: {len(orphan_stems):,} orphan images "
        f"(pool {len(idx):,} - registered {len(registered):,})")
    excluded = []
    if orphan_stems and os.path.isfile(YELLOW):
        olist = write_list(os.path.join(WORK, "orphans_all.txt"),
                           [idx[s] for s in orphan_stems])
        ycsv = os.path.join(WORK, "orphan_yellow.csv")
        # Tether-strict profile (calibration 2026-08-11): hue 40-70 deg,
        # sat >= 0.65 suppresses quagga-mussel false positives.
        r = subprocess.run(
            [sys.executable, YELLOW, "--files", olist,
             "--hue-min", "40", "--hue-max", "70", "--sat-min", "0.65",
             "--threshold", str(YELLOW_THRESHOLD), "--out", ycsv],
            capture_output=True, text=True, creationflags=0x08000000)
        if r.returncode == 0 and os.path.isfile(ycsv):
            for ln in open(ycsv, encoding="utf-8").read().splitlines()[1:]:
                p, frac = ln.rsplit(",", 1)
                if float(frac) >= YELLOW_THRESHOLD:
                    excluded.append(p)
            if len(excluded) > YELLOW_CAP_FRACTION * len(orphan_stems):
                log(f"O: yellow screen flagged {len(excluded):,} "
                    f"(> {YELLOW_CAP_FRACTION:.0%} of orphans) - "
                    "DISTRUSTING the screen, excluding nothing; "
                    "list saved for morning review")
                excluded = []
        else:
            log(f"O: yellow screen unavailable ({r.returncode}) - "
                "no exclusions")
    excl_set = {os.path.splitext(os.path.basename(p))[0].lower()
                for p in excluded}
    log(f"O: excluding {len(excl_set):,} tether-flagged orphan(s) from "
        "the add (files NOT deleted; list in orphan_yellow.csv)")
    accepted = [idx[s] for s in orphan_stems if s not in excl_set]

    # A: add accepted orphans with priors, ALL-FEATURES
    if accepted:
        alist = write_list(os.path.join(WORK, "orphans_add.imagelist"),
                           accepted)
        checkpoint("night_pre_add")
        if not night("addorphans", SCENE, alist, NAV, FLPARAMS):
            abort("addorphans failed - checkpoint night_pre_add")
        log(f"A: added {len(accepted):,} orphans (ALL FEATURES + priors)")
    else:
        log("A: no orphans to add")

    # S: seed-growth loop - largest component disabled throughout
    baseline = set(registered)
    prev_tag = "night_pre_seed"
    checkpoint(prev_tag)
    rollbacks = 0
    for p in range(1, MAX_SEED_PASSES + 1):
        largest = comps[0]
        small_stems = set()
        for name, cnt, stems in comps[1:]:
            small_stems |= stems
        enable = sorted({idx[s] for s in small_stems if s in idx}
                        | set(accepted))
        if not enable:
            log(f"S{p}: nothing outside the largest component to grow - done")
            break
        elist = write_list(os.path.join(WORK, f"seed_{p}.imagelist"), enable)
        log(f"S{p}: aligning {len(enable):,} enabled images "
            f"(largest {largest[0]}={largest[1]:,} disabled)")
        tag = f"night_seed_{p}"
        checkpoint(tag)
        if not night("seedpass", SCENE, elist, ALIGN_PARAMS):
            log(f"S{p}: pass workflow failed - restoring {tag}")
            restore(tag)
            rollbacks += 1
            if rollbacks >= ROLLBACK_STORM:
                log("S: rollback storm - stopping seed loop (a finding, "
                    "not something to push through)")
                break
            continue
        comps2, reg2 = census(f"seed_{p}")
        if comps2 is None:
            restore(tag)
            break
        lost = baseline - reg2
        if lost or len(reg2) < len(baseline):
            log(f"S{p}: REJECT - {len(lost)} previously-registered "
                f"image(s) lost / count {len(reg2):,} < {len(baseline):,} "
                f"- restoring {tag}")
            restore(tag)
            rollbacks += 1
            if rollbacks >= ROLLBACK_STORM:
                log("S: rollback storm - stopping seed loop")
                break
            continue
        gained = len(reg2) - len(baseline)
        log(f"S{p}: ACCEPT - +{gained:,} newly registered "
            f"({len(reg2):,} total)")
        rollbacks = 0
        comps, registered, baseline = comps2, reg2, set(reg2)
        if gained == 0:
            log("S: converged (no growth) - seed loop done")
            break

    # M: final merge of largest + the grown rest
    log("M: enabling ALL and attempting final consolidation")
    checkpoint("night_pre_merge")
    merged_ok = False
    if night("mergefinal", SCENE, ALIGN_PARAMS, "merge"):
        comps3, reg3 = census("merge_rigid")
        if comps3 is not None and not (baseline - reg3):
            comps, registered, baseline = comps3, reg3, set(reg3)
            merged_ok = len(comps) < 2
        else:
            restore("night_pre_merge")
    if not merged_ok and len(comps) >= 2:
        log("M: still split after rigid merge - ONE align rung")
        checkpoint("night_pre_align_merge")
        if night("mergefinal", SCENE, ALIGN_PARAMS, "align"):
            comps4, reg4 = census("merge_align")
            if comps4 is not None and not (baseline - reg4) \
                    and len(reg4) >= len(baseline):
                comps, registered = comps4, reg4
            else:
                log("M: align rung shrank the census - restoring")
                restore("night_pre_align_merge")

    # R: report
    stop.set()
    night("saveonly", SCENE)
    report = {
        "finished": f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}",
        "registered": len(registered),
        "components": [{"name": n, "count": c} for n, c, _ in comps],
        "orphans_excluded_yellow": len(excl_set),
        "scene": SCENE,
    }
    with open(os.path.join(WORK, "NIGHT_REPORT.json"), "w",
              encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    log(f"NIGHT DONE: {len(comps)} component(s), "
        f"{len(registered):,} registered - report written")


if __name__ == "__main__":
    main()
