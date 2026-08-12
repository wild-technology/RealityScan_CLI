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


_OP_IN_FLIGHT = threading.Lock()
METRICS_CSV = os.path.join(WORK, "metrics.csv")


def _mem_gb():
    """(rsgui_ws_gb, commit_used_gb) - cheap enough for op boundaries
    and a 30 s peak sampler (owner 2026-08-11: track time AND memory
    per step)."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "$p = Get-Process RealityScan -ErrorAction SilentlyContinue "
             "| Sort-Object WorkingSet64 -Descending "
             "| Select-Object -First 1; "
             "$os = Get-CimInstance Win32_OperatingSystem; "
             "[math]::Round($p.WorkingSet64/1GB,2); "
             "[math]::Round(($os.TotalVirtualMemorySize"
             "-$os.FreeVirtualMemory)/1MB,1)"],
            capture_output=True, text=True, timeout=30,
            creationflags=0x08000000)
        ws, commit = [float(x) for x in out.stdout.split()]
        return ws, commit
    except Exception:
        return 0.0, 0.0


def night(mode, *args):
    """One NightGrow.bat primitive against the live instance. Serialized:
    the hourly saver skips its save when an op holds the lock, so saves
    never stack behind long aligns/censuses (save time scales with the
    component count - owner note 2026-08-11; every mutating mode already
    saves on completion). Per-op wall time and memory (RSGUI working
    set + system commit, with 30 s peak sampling) land in the log and
    metrics.csv."""
    with _OP_IN_FLIGHT:
        clear_errors()
        t0 = time.time()
        ws0, cm0 = _mem_gb()
        peak = {"ws": ws0, "cm": cm0}
        done = threading.Event()

        def sampler():
            while not done.wait(30):
                ws, cm = _mem_gb()
                peak["ws"] = max(peak["ws"], ws)
                peak["cm"] = max(peak["cm"], cm)

        st = threading.Thread(target=sampler, daemon=True)
        st.start()
        result = CLI.run_attach_script("NightGrow.bat", [mode, *args],
                                       LOGS, instance=INSTANCE)
        done.set()
        mins = (time.time() - t0) / 60
        ws1, cm1 = _mem_gb()
        peak["ws"] = max(peak["ws"], ws1)
        peak["cm"] = max(peak["cm"], cm1)
        new_csv = not os.path.isfile(METRICS_CSV)
        with open(METRICS_CSV, "a", encoding="utf-8", newline="") as f:
            if new_csv:
                f.write("timestamp,mode,ok,minutes,ws_before_gb,"
                        "ws_after_gb,ws_peak_gb,commit_before_gb,"
                        "commit_after_gb,commit_peak_gb\r\n")
            f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S},{mode},"
                    f"{int(result.success)},{mins:.1f},{ws0},{ws1},"
                    f"{peak['ws']},{cm0},{cm1},{peak['cm']}\r\n")
        if not result.success:
            log(f"NightGrow {mode} FAILED after {mins:.1f} min "
                f"(WS {ws0}->{ws1} peak {peak['ws']} GB; commit {cm0}->"
                f"{cm1} peak {peak['cm']} GB): "
                f"{result.errors or result.return_code} "
                f"(log: {result.log_path})")
            return False
        log(f"NightGrow {mode} ok ({mins:.1f} min; WS {ws0}->{ws1} peak "
            f"{peak['ws']} GB; commit {cm0}->{cm1} peak {peak['cm']} GB)")
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
    components = [(name, count, stems_set)] largest first.

    RESUMES from a completed same-tag capture (marker file written after
    a successful peel): a full peel measured 135 min, and a driver
    restart between census and the next mutation must not repeat it.
    Tags after mutations are unique per pass, so reuse is safe."""
    outdir = os.path.join(WORK, f"census_{tag}")
    done_marker = os.path.join(outdir, "CAPTURE_COMPLETE")
    if not os.path.isfile(done_marker):
        if os.path.isdir(outdir):
            shutil.rmtree(outdir)
        os.makedirs(outdir)
        if not night("census", SCENE, outdir, ZONES, POOL):
            return None, None
        open(done_marker, "w").close()
    else:
        log(f"census {tag}: reusing completed capture")
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


def delete_component(name):
    """Delete a component by name - the name rides via env: names like
    'Component 23 (1)' carry cmd metacharacters that can never be .bat
    arguments (hard rule 8; assert_bat_safe refused them 2026-08-12)."""
    os.environ["RS_NG_COMPNAME"] = name
    try:
        return night("delete2nd", SCENE)
    finally:
        os.environ.pop("RS_NG_COMPNAME", None)


def census_light(tag):
    """Registered-set-only census: ONE exportXMP sweep, non-destructive,
    minutes not hours (a full 24-component peel measured 135 min -
    2026-08-12). Enough for the never-shrink verdict; component
    membership comes from the last FULL census."""
    outdir = os.path.join(WORK, f"light_{tag}")
    if os.path.isdir(outdir):
        shutil.rmtree(outdir)
    os.makedirs(outdir)
    if not night("censuslight", SCENE, outdir, ZONES, POOL):
        return None
    stems = {os.path.splitext(f)[0].lower()
             for f in os.listdir(outdir) if f.lower().endswith(".xmp")}
    log(f"light census {tag}: {len(stems):,} registered")
    return stems


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
        if _OP_IN_FLIGHT.locked():
            # An op is running; every mutating mode saves on completion,
            # so skipping here loses nothing and never queues a save
            # behind a long align/census (component-count save cost).
            log("hourly save skipped (operation in flight)")
            continue
        log("hourly save")
        night("saveonly", SCENE)


def tidy_components(comps):
    """Delete components fully CONTAINED in a larger one (align/merge
    leaves superseded SOURCE components in the scene - FINDINGS; they
    bloat every save, which scales with component count). Containment is
    manifest-verified from the census stems; the largest component is
    never deleted. Returns the tidied census list."""
    keep = [comps[0]]
    victims = []
    for name, cnt, stems in comps[1:]:
        container = next((k for k in comps
                          if k[0] != name and k[1] > cnt
                          and stems <= k[2]), None)
        if container is not None:
            victims.append((name, cnt, container[0]))
        else:
            keep.append((name, cnt, stems))
    for name, cnt, cname in victims:
        log(f"tidy: deleting {name} ({cnt:,} cams - contained in {cname})")
        if not delete_component(name):
            log(f"tidy: delete of {name} failed - leaving it")
            keep.append(next(c for c in comps if c[0] == name))
    if victims:
        keep.sort(key=lambda c: -c[1])
    return keep


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
        if not delete_component(second[0]):
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

    # S: seed-growth loop - largest component disabled throughout.
    # Verdicts ride the LIGHT census (one export sweep, minutes); the
    # 135-minute full peel refreshes membership + tidies only every
    # FULL_EVERY passes and at loop end (measured 2026-08-12).
    FULL_EVERY = 3
    baseline = set(registered)
    largest_members = set(comps[0][2])
    largest_label = f"{comps[0][0]}={comps[0][1]:,}"
    checkpoint("night_pre_seed")
    rollbacks = 0
    accepted_since_full = 0
    for p in range(1, MAX_SEED_PASSES + 1):
        # Enable EVERYTHING except the last-known largest membership:
        # covers small components AND images grown since the last full
        # peel (they are in no recorded component) AND added orphans.
        enable = sorted({idx[s] for s in (baseline - largest_members)
                         if s in idx} | set(accepted))
        if not enable:
            log(f"S{p}: nothing outside the largest component to grow - done")
            break
        elist = write_list(os.path.join(WORK, f"seed_{p}.imagelist"), enable)
        log(f"S{p}: aligning {len(enable):,} enabled images "
            f"(largest {largest_label} disabled)")
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
        reg2 = census_light(f"seed_{p}")
        if reg2 is None:
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
        registered, baseline = reg2, set(reg2)
        accepted_since_full += 1
        if accepted_since_full >= FULL_EVERY:
            comps2, regf = census(f"seed_full_{p}")
            if comps2 is not None:
                comps, registered, baseline = comps2, regf, set(regf)
                comps = tidy_components(comps)
                largest_members = set(comps[0][2])
                largest_label = f"{comps[0][0]}={comps[0][1]:,}"
                accepted_since_full = 0
        if gained == 0:
            log("S: converged (no growth) - seed loop done")
            break
    # Refresh membership before the merge stage if the loop ended
    # between full peels (merge verdicts + tidy need real membership).
    if accepted_since_full:
        comps2, regf = census("seed_final")
        if comps2 is not None:
            comps, registered, baseline = comps2, regf, set(regf)
            comps = tidy_components(comps)

    # M: final merge of largest + the grown rest
    log("M: enabling ALL and attempting final consolidation")
    checkpoint("night_pre_merge")
    merged_ok = False
    if night("mergefinal", SCENE, ALIGN_PARAMS, "merge"):
        comps3, reg3 = census("merge_rigid")
        if comps3 is not None and not (baseline - reg3):
            comps, registered, baseline = comps3, reg3, set(reg3)
            comps = tidy_components(comps)
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
                comps = tidy_components(comps)
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
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # A crash must be VISIBLE to the monitors (the 2026-08-11
        # checkpoint .lock crash died silently into the console log).
        import traceback
        log("ABORT: unhandled exception\n" + traceback.format_exc())
        raise
