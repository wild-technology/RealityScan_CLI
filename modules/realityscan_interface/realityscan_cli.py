"""Unified execution layer for the RealityScan 2.2 CLI.

Every script in this repository that drives RealityScan must go through this
module so that launching, monitoring, error detection, and race-condition
handling behave identically everywhere.

How execution works
-------------------
The batch scripts in ``RS_CLI/Scripts`` boot one persistent *headless*
RealityScan instance (named ``RS1`` by default) and delegate each operation
to it with ``-delegateTo``. Delegated commands are *queued* — the delegating
process returns as soon as the command is handed over, NOT when the
operation finishes. Synchronisation therefore uses three cooperating
mechanisms, in line with RealityScan's own CLI facilities:

1. ``-waitCompleted <instance>`` after every delegated command (issued twice
   with a short grace period in between, because ``-waitCompleted`` can
   return prematurely when it runs before the instance has picked the
   queued command up — a race we have hit in production).
2. RealityScan's built-in process trigger: the instance is started with
   ``appProcessAction=ExecuteProgram`` and ``appProcessExecCmd`` pointing at
   ``RS_CLI/Errors/ErrorWriter.bat``. RealityScan itself invokes that hook
   whenever a process finishes and passes ``$(processResult)``. Every
   completion is appended to ``results.log``; failures are appended to
   ``errors.txt``. This is the source of truth for per-operation success —
   the batch scripts abort as soon as ``errors.txt`` becomes non-empty.
3. ``-writeProgress progress.txt`` on the instance, which this module tails
   to report activity and to warn about stalls. There is deliberately NO
   overall timeout: alignment/reconstruction on large datasets legitimately
   runs for many hours.

Race-condition rules enforced here:
- A per-instance lock file prevents two orchestrators from driving the same
  instance name concurrently.
- Marker files (``progress_<instance>.txt``, ``errors_<instance>.txt``,
  ``results_<instance>.log``) are namespaced per instance and cleared
  before every run, so parallel instances and previous runs can never be
  misread as the current run's state.
- After a workflow finishes, we verify via ``-getStatus`` that the instance
  actually shut down before the next workflow starts, so consecutive runs
  can never share (and contaminate) a scene.
- Completion is never inferred from process *names* (the pre-2.x code
  polled ``tasklist`` for ``RealityCapture.exe``, which silently matched
  nothing once the executable became ``RealityScan.exe``).

Multi-GPU
---------
RealityScan uses every CUDA GPU by default. To pin an instance to specific
GPUs (e.g. to run one instance per GPU), set ``gpu_devices`` in
``rs_settings.json`` under the ``realityscan`` section (e.g. ``"0,1"``), or
pass ``gpu_devices`` to :meth:`RealityScanCLI.run_batch_script`. The value
is exported as ``CUDA_VISIBLE_DEVICES``/``RS_GPU_DEVICES`` for the launched
instance. Give each concurrent instance a unique ``instance_name``.
"""

from __future__ import annotations

import csv
import io
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping

try:
    from module_base.settings_store import SettingsStore, realityscan_env
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))
    from module_base.settings_store import SettingsStore, realityscan_env

_THIS_DIR = os.path.dirname(os.path.realpath(__file__))
SCRIPTS_DIR = os.path.join(_THIS_DIR, 'RS_CLI', 'Scripts')
METADATA_DIR = os.path.join(_THIS_DIR, 'RS_CLI', 'Metadata')
ERRORS_DIR = os.path.join(_THIS_DIR, 'RS_CLI', 'Errors')
ERROR_HELPERS_DIR = ERRORS_DIR
# Shared across checkouts. Anchor files are NEVER unlinked: doing so lets a
# second process lock a different inode while the first still holds its lock.
LOCKS_DIR = os.path.join(
    os.environ.get('LOCALAPPDATA') or os.path.join(os.path.expanduser('~'), '.cache'),
    'RealityScanCLI', 'locks')
_RETAINED_RUNS = {}  # Strong references keep OS leases alive after interruption.
_RETAINED_GUARD = threading.RLock()

DEFAULT_INSTANCE_NAME = 'RS1'

# Console-subsystem children (tasklist, cmd) each pop a visible console
# window when their parent has none - over a long run that is hundreds of
# flashing windows stealing focus (owner report, 2026-07-23). Suppress on
# every helper subprocess; harmless for GUI-subsystem RealityScan.exe.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

# Only supported 2.2 locations; filenames/directories do not prove the version.
EXECUTABLE_CANDIDATES = [
    r'C:\Program Files\Epic Games\RealityScan_2.2\RealityScan.exe',
    r'C:\Program Files\Capturing Reality\RealityScan 2.2\RealityScan.exe',
]

# How long progress may stay silent before we log a stall warning. This is
# a warning only — large datasets can legitimately be quiet for a long time.
STALL_WARNING_SECONDS = 2 * 60 * 60

# ---------------------------------------------------------------------------
# FROZEN-PROGRESS detection (NA165/H2060 zone_2, 2026-09-07)
# ---------------------------------------------------------------------------
# The silence-based guard above cannot detect the failure that actually cost
# 14.2 h. It keys on the progress line CHANGING; during zone_2's freeze the
# line kept changing while the work did not:
#
#   ... 0.61 39859.34 25128.00 #progress      <- fraction unchanged
#   ... 0.61 40459.34 25506.00 #timeout       <- 600 s later, ignored as activity
#   ... 0.61 40468.86 25512.00 #progress      <- re-arms last_activity
#
# The elapsed counter advances every line, so the text is never equal to the
# previous text, and the non-#timeout records arrived at most 800 s apart
# against a 7,200 s threshold. The timer re-armed forever. Raising or lowering
# STALL_WARNING_SECONDS cannot fix it: any threshold that would have fired must
# sit below 800 s, and a healthy align is legitimately quiet for one 600 s
# -writeProgress heartbeat (measured: zone_1's longest genuine plateau was
# 600.0 s and 603.2 s across two runs).
#
# What DOES separate them is the fraction itself, at full precision.
# RealityScan computes remaining = elapsed * (1 - p) / p exactly, so
#     p = elapsed / (elapsed + remaining)
# recovers it ~100x finer than the 2-decimal figure in the line. Measured over
# the freeze: p spanned 0.615009278..0.615015234 - a spread of 6.0e-6 that is
# NON-MONOTONE (it drifts backwards as well as forwards), i.e. estimator jitter
# around a constant, not slow progress. In both healthy zone_1 runs EVERY
# progress record carried a strictly new fraction: 182 records, 182 distinct
# values, zero repeats.
#
# Window: 3,600 s of the OPERATION'S OWN elapsed clock, never wall clock, so
# this remains a non-progress test and not a timeout (hard rule 3). Measured
# sweep over the real logs:
#     900 s  -> FALSE POSITIVE on a healthy zone_1 run
#   1,800 s  -> flags zone_2 while it was still genuinely advancing
#   3,600 s  -> clears zone_1 by 255-568x, flags zone_2 2.2 h before the
#               operator killed it, and clears zone_2's own longest RECOVERED
#               freeze (1,825 s) by 2.0x
# Epsilon 1e-4 sits 17x above the observed jitter and below the smallest real
# increment seen just before the freeze (~9e-5). An equality test would never
# fire - all 35 frozen values differ at 1e-9.
PROGRESS_STALL_WINDOW_SECONDS = 3600.0
PROGRESS_STALL_EPSILON = 1e-4


def parse_progress_line(line: str):
    """(alg_id, fraction, elapsed_s, remaining_s) from a progress record.

    Shape: ``<algId> <fraction> <elapsed> <remaining> #progress|#timeout``.
    Returns None when the line is not a progress record or is malformed - the
    monitor must never die on an unexpected line.
    """
    if not line:
        return None
    parts = line.split()
    for i, tok in enumerate(parts):
        try:
            frac = float(tok)
        except ValueError:
            continue
        if not (0.0 <= frac <= 1.0) or '.' not in tok:
            continue
        if i == 0 or i + 2 >= len(parts):
            continue
        try:
            alg = int(parts[i - 1])
            elapsed = float(parts[i + 1])
            remaining = float(parts[i + 2])
        except ValueError:
            continue
        if not math.isfinite(elapsed) or not math.isfinite(remaining):
            continue
        return alg, frac, elapsed, remaining
    return None


class _ProgressTracker:
    """Tracks the recovered fraction per operation and reports a freeze.

    A changed algorithm ID or an elapsed-clock rollback starts a generation.
    Algorithm IDs identify operation kinds, not unique invocations.
    """

    def __init__(self, window=PROGRESS_STALL_WINDOW_SECONDS,
                 epsilon=PROGRESS_STALL_EPSILON):
        self.window = window
        self.epsilon = epsilon
        self.alg = None
        self.generation = 0
        self.samples = []          # (op_elapsed, recovered_p)

    @staticmethod
    def recovered_fraction(elapsed, remaining):
        """p = elapsed / (elapsed + remaining), the unrounded fraction.

        RealityScan's own remaining estimate is elapsed*(1-p)/p, so this
        inverts it exactly. Returns None when the pair carries no information
        (both zero at operation start, or a negative remaining).
        """
        total = elapsed + remaining
        if not math.isfinite(total) or total <= 0 or elapsed < 0 or remaining < 0:
            return None
        return elapsed / total

    def update(self, line):
        """Feed one progress line. Returns frozen-seconds when the operation
        has not advanced across the whole window, else None."""
        parsed = parse_progress_line(line)
        if parsed is None:
            return None
        alg, _frac, elapsed, remaining = parsed
        if alg != self.alg or (self.samples and elapsed < self.samples[-1][0]):
            self.alg = alg
            self.generation += 1
            self.samples = []
        p = self.recovered_fraction(elapsed, remaining)
        if p is None:
            return None
        self.samples.append((elapsed, p))
        # Keep one sample older than the window so the comparison spans it.
        cutoff = elapsed - self.window
        while len(self.samples) > 2 and self.samples[1][0] <= cutoff:
            self.samples.pop(0)
        oldest_e, _ = self.samples[0]
        span = elapsed - oldest_e
        if span < self.window:
            return None
        values = [value for _, value in self.samples]
        if max(values) - min(values) < self.epsilon:
            return span
        return None
# Near-OOM, RealityScan slows to a crawl WITHOUT crashing and without
# spilling to disk (owner-observed, 2026-07-24) — in the progress feed
# that is indistinguishable from a hang or a quiet compute phase, so the
# monitor samples available RAM and warns when it gets low.
LOW_MEMORY_WARN_GB = 4.0


def _memory_status() -> dict | None:
    """Physical RAM and commit-charge figures in GiB (Windows), or None.

    One GlobalMemoryStatusEx call - microseconds, no subprocess. Commit
    charge is included because a run can exhaust commit while physical RAM
    still looks comfortable.
    """
    if os.name != 'nt':
        return None
    import ctypes

    class _MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
            ('ullTotalPhys', ctypes.c_uint64), ('ullAvailPhys', ctypes.c_uint64),
            ('ullTotalPageFile', ctypes.c_uint64), ('ullAvailPageFile', ctypes.c_uint64),
            ('ullTotalVirtual', ctypes.c_uint64), ('ullAvailVirtual', ctypes.c_uint64),
            ('ullAvailExtendedVirtual', ctypes.c_uint64)]

    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(_MemoryStatusEx)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    gb = 1024 ** 3
    return {
        'ram_avail_gb': status.ullAvailPhys / gb,
        'ram_total_gb': status.ullTotalPhys / gb,
        'mem_load_pct': float(status.dwMemoryLoad),
        # "PageFile" in this struct is the system commit limit/available,
        # not a paging-file-only figure.
        'commit_avail_gb': status.ullAvailPageFile / gb,
        'commit_total_gb': status.ullTotalPageFile / gb,
    }


def _available_ram_gb() -> float | None:
    """Available physical RAM in GiB (Windows), or None."""
    status = _memory_status()
    return None if status is None else status['ram_avail_gb']


class _CpuSampler:
    """System-wide CPU utilisation between successive calls.

    Uses GetSystemTimes tick counters, so a sample costs one syscall and no
    process spawn - `wmic`/`typeperf`/`Get-Counter` would each cost 50-200 ms
    and pop a console window under a hidden parent.
    """

    def __init__(self) -> None:
        self._prev = None

    def _ticks(self):
        if os.name != 'nt':
            return None
        import ctypes
        idle, kernel, user = (ctypes.c_uint64(), ctypes.c_uint64(),
                              ctypes.c_uint64())
        if not ctypes.windll.kernel32.GetSystemTimes(
                ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        # kernel time INCLUDES idle time on Windows.
        return idle.value, kernel.value + user.value

    def percent(self) -> float | None:
        """CPU busy percent since the previous call; None on the first."""
        now = self._ticks()
        if now is None:
            return None
        prev, self._prev = self._prev, now
        if prev is None:
            return None
        idle_delta = now[0] - prev[0]
        total_delta = now[1] - prev[1]
        if total_delta <= 0:
            return None
        return max(0.0, min(100.0, 100.0 * (1.0 - idle_delta / total_delta)))
PROGRESS_POLL_SECONDS = 2.0
# Resource trace cadence. The monitor loop already wakes every
# PROGRESS_POLL_SECONDS, so a sample is two ctypes syscalls plus one buffered
# CSV line - far too cheap to matter against a multi-hour GPU workload, while
# 30 s is fine resolution for the memory ramp that precedes an OOM crash.
RESOURCE_SAMPLE_SECONDS = 30.0
# Closing a very large scene after -quit can take a long time; override via
# "realityscan"/"shutdown_timeout" in rs_settings.json if 15 min is not enough.
SHUTDOWN_VERIFY_TIMEOUT_SECONDS = 900
STATUS_CALL_TIMEOUT_SECONDS = 60

# ---------------------------------------------------------------------------
# Workflow-argument validation (the ONE boundary, hard rule 1)
# ---------------------------------------------------------------------------
# Python's list2cmdline quotes an argument only when it contains WHITESPACE,
# and cmd re-parses even a quoted argument, so these characters are silently
# eaten, split on, or executed when a path or name crosses into a .bat.
# Measured with an echo-only .bat (audit 2026-08-07), every case rc=0:
#   'D:\NA167 Wreck & Debris\exports' -> ARG1='D:\NA167 Wreck ', the rest RUN
#   'D:\NA167^b\exports'              -> 'D:\NA167b\exports'  (caret eaten)
#   'D:\dive\a=b\exports'             -> split; every later positional shifts
#   'D:\dive\with,comma\final'        -> split
# CLAUDE.md hard rule 8 names this trap for delimited DATA; nothing enforced
# it for PATHS, which is exactly what a fresh user supplies ("NA167, dive 2",
# "Wreck & Debris" are ordinary expedition folder names).
#
# ':' and '\' are absent deliberately - every argument here is a Windows
# path. '%' and '!' ARE included: %VAR% expands at parse time and ! expands
# under EnableDelayedExpansion, which several workflow scripts set.
CMD_METACHARACTERS = frozenset('&^|<>()=,;%!"`')


def assert_bat_safe(args, script_name: str = '') -> None:
    """Refuse to hand cmd an argument it would silently corrupt.

    Raises ValueError naming the argument, the offending characters and the
    two legitimate ways across the boundary (rename, or pass by file/env
    var). Called by BOTH run_batch_script and run_attach_script, so every
    driver - finish_model, export_deliverables, run_models, merge_zones,
    grow_zone and anything written later - is covered by one check.
    """
    for index, arg in enumerate(args, start=1):
        bad = sorted(set(str(arg)) & CMD_METACHARACTERS)
        if bad:
            raise ValueError(
                f'{script_name or "workflow"} argument {index} contains cmd '
                f'metacharacter(s) {bad} that cmd splits, eats or EXECUTES '
                f'silently (the process still returns 0): {arg!r}. '
                'Rename the folder/component, or pass the value through a '
                'file or an environment variable (CLAUDE.md hard rule 8).')


def set_project_save_env(zone_images_root: str, label: str) -> str:
    """Arm the daily project-save schema for the workflow scripts.

    Projects live in RC_projects ONE LEVEL UP from the zone image
    directory, one copy per day per scene named
    {expedition_dive}_{zone|merged}_YYYYMMDD.rsproj (owner requirement
    2026-07-23). The scripts compose the filename from
    RS_PROJECT_LABEL/RS_PROJECT_DATE; scenes re-saved later the same day
    overwrite that day's copy, a new day starts a fresh copy.

    Returns the RC_projects directory path.
    """
    projects_dir = os.path.join(
        os.path.dirname(os.path.normpath(zone_images_root)), 'RC_projects')
    os.environ['RS_PROJECTS_DIR'] = projects_dir
    os.environ['RS_PROJECT_LABEL'] = label
    os.environ['RS_PROJECT_DATE'] = time.strftime('%Y%m%d')
    return projects_dir


class RunControl:
    """Thread-safe cancellation request for one workflow.

    A request stops subsequent workflows, not the active .bat. The driver keeps
    monitoring with its OS lease held until quiescence. abort_current is allowed
    only for an owned boot, after arming the sticky batch dispatch sentinel.
    File abort_current shares these semantics across processes. File after_step
    belongs to the parent Python-stage dispatcher and does not fail child work.
    """

    def __init__(self):
        self._requested = threading.Event()
        self._guard = threading.Lock()
        self._reason = ''
        self._mode = 'after_step'

    def request_cancel(self, reason: str = 'user', *, mode: str = 'after_step') -> bool:
        if mode not in ('after_step', 'abort_current'):
            raise ValueError(f'Unknown cancellation mode: {mode}')
        with self._guard:
            if self._requested.is_set() and (self._mode == mode or self._mode == 'abort_current'):
                return False
            self._reason = str(reason)
            self._mode = mode
            self._requested.set()
            return True

    @property
    def cancellation_requested(self) -> bool:
        return self._requested.is_set()

    @property
    def reason(self) -> str:
        return self._reason

    @property
    def mode(self) -> str:
        return self._mode


@dataclass(frozen=True)
class RunEvent:
    run_id: str
    sequence: int
    kind: str
    instance: str
    data: Mapping[str, object]
    parent_run_id: str = ''

    def as_dict(self) -> dict:
        return {'run_id': self.run_id, 'sequence': self.sequence,
                'kind': self.kind, 'instance': self.instance,
                'data': dict(self.data), 'parent_run_id': self.parent_run_id}


class _OSLock:
    """Nonblocking shared/exclusive OS lock on a permanent anchor file."""

    def __init__(self, path: str, *, shared: bool = False):
        self.file = open(path, 'a+b', buffering=0)
        try:
            if os.name == 'nt':
                import ctypes
                import msvcrt
                from ctypes import wintypes

                class Overlapped(ctypes.Structure):
                    _fields_ = [('Internal', ctypes.c_size_t),
                                ('InternalHigh', ctypes.c_size_t),
                                ('Offset', wintypes.DWORD),
                                ('OffsetHigh', wintypes.DWORD),
                                ('hEvent', wintypes.HANDLE)]

                kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                lock = kernel.LockFileEx
                lock.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                 wintypes.DWORD, wintypes.DWORD,
                                 wintypes.DWORD, ctypes.POINTER(Overlapped)]
                lock.restype = wintypes.BOOL
                self.overlapped = Overlapped()
                # FAIL_IMMEDIATELY, plus EXCLUSIVE_LOCK for a writer.
                if not lock(msvcrt.get_osfhandle(self.file.fileno()),
                            1 if shared else 3, 0, 1, 0,
                            ctypes.byref(self.overlapped)):
                    raise ctypes.WinError(ctypes.get_last_error())
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_NB |
                            (fcntl.LOCK_SH if shared else fcntl.LOCK_EX))
        except BaseException:
            self.file.close()
            raise

    def close(self):
        # Closing the handle releases the OS lock on both platforms.
        self.file.close()


@dataclass
class _Lease:
    token: str
    gate: _OSLock
    anchor: _OSLock
    journal: str
    marker: str
    retained: bool = False


@dataclass
class _Run:
    run_id: str
    instance: str
    attach: bool
    environment: Mapping[str, str]
    control: RunControl
    observer: Callable[[RunEvent], None] | None
    started: float = field(default_factory=time.monotonic)
    sequence: int = 0
    process: object = None
    log_path: str | None = None
    resource_path: str | None = None
    status: str = 'prepared'
    launch_attempted: bool = False
    parent_run_id: str = ''
    control_file: str | None = None
    event_file: str | None = None
    notified_mode: str = ''
    control_error: str = ''
    abort_sentinel: str | None = None
    abort_initial_sent: bool = False
    abort_final_sent: bool = False
    abort_quiescent: bool = False
    abort_wait_observed: bool = False
    shutdown_sent: bool = False
    idle_revision: int | None = None
    abort_refused: bool = False
    monitor_error: str = ''
    startup_refused_file: str | None = None
    boot_owned_file: str | None = None
    ownership_refused: bool = False
    file_after_step_requested: bool = False
    monitoring: bool = True
    failure_cleanup: bool = False


@dataclass
class WorkflowResult:
    success: bool
    return_code: int | None
    log_path: str = None
    errors: str = ''
    completed_processes: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    run_id: str = ''
    status: str = 'finished'
    cancellation_requested: bool = False
    ownership_retained: bool = False
    resource_path: str | None = None


class RealityScanCLI:
    """Shared launcher/monitor for every RealityScan CLI workflow."""

    def __init__(self, logger, settings: SettingsStore = None, instance_name: str = None):
        self.logger = logger
        self.settings = settings or SettingsStore()
        # Resolution order: constructor arg -> RS_INSTANCE env var ->
        # rs_settings.json -> default. The env var was previously only ever
        # WRITTEN (for the .bat layer), never read - so a driver exporting
        # RS_INSTANCE=RS2 for isolation silently ran on whatever the settings
        # file held, and could -quit a live instance it did not own
        # (2026-07-28: an overlap-probe session running from this checkout
        # landed on RS1 while it was the production instance; audit #19).
        self.instance_name = (
            instance_name
            or os.environ.get('RS_INSTANCE')
            or self.settings.get('realityscan', 'instance_name')
            or DEFAULT_INSTANCE_NAME
        )

        # Pin machine values without publishing them into the application's
        # environment. Otherwise constructing instance A changes B's defaults.
        # Science flags are still captured at workflow invocation, because
        # existing drivers set those after constructing their CLI object.
        machine = {key: str(value) for key, value in
                   realityscan_env(self.settings).items()}
        machine['RS_INSTANCE'] = self.instance_name
        self._machine_env = MappingProxyType(machine)
        self._leases = {}
        self._runs = {}
        self._runtime_guard = threading.RLock()
        # Bind executable selection to this CLI's machine snapshot. A project
        # override wins over saved global settings; strict children inherit none.
        self._executable_override = os.environ.get('RS_EXECUTABLE')
        self._configured_executable = (None if os.environ.get('RS_NO_SETTINGS_INHERITANCE') == '1'
                                       else self.settings.get('realityscan', 'executable'))
        self._validated_executable = None
        self._runtime_context = {key: os.environ[key] for key in (
            'RS_RUN_ID', 'RS_RUNTIME_ROOT', 'RS_ERRORS_DIR', 'RS_CONTROL_FILE', 'RS_EVENT_FILE')
            if key in os.environ}
        root = self._runtime_context.get('RS_RUNTIME_ROOT')
        errors = self._runtime_context.get('RS_ERRORS_DIR')
        self._errors_dir = ERRORS_DIR
        if root is not None or errors is not None:
            run_id = self._runtime_context.get('RS_RUN_ID', '')
            if (not root or not os.path.isabs(root) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', run_id)
                    or Path(root).name != run_id or Path(root).parent.name.casefold() != 'tmp'
                    or Path(root).parent.parent.name.casefold() != 'proc'):
                raise ValueError('Runtime outputs require RS_RUNTIME_ROOT=<project>/proc/tmp/<RS_RUN_ID>')
            marker_dir = os.path.join(root, 'markers')
            if errors is not None and (not os.path.isabs(errors)
                    or os.path.normcase(os.path.abspath(errors)) != os.path.normcase(os.path.abspath(marker_dir))):
                raise ValueError('RS_ERRORS_DIR must be exactly RS_RUNTIME_ROOT/markers')
            assert_bat_safe([root, marker_dir], 'runtime output paths')
            self._runtime_context['RS_ERRORS_DIR'] = marker_dir
            self._errors_dir = marker_dir
            self._validate_runtime_paths()
        self._runtime_context = MappingProxyType(dict(self._runtime_context))

    def _validate_runtime_paths(self):
        root = self._runtime_context.get('RS_RUNTIME_ROOT')
        if not root:
            return
        for leaf in (Path(root) / 'markers', Path(root) / 'models'):
            for path in (leaf, *leaf.parents):
                if path.is_symlink() or path.is_junction():
                    raise ValueError(f'Runtime output path is redirected: {path}')
                if path.exists() and not path.is_dir():
                    raise ValueError(f'Runtime output parent is not a directory: {path}')

    def _prepare_runtime_paths(self) -> dict:
        """Stage immutable canonical hooks into project-owned output directories."""
        if not self._runtime_context.get('RS_RUNTIME_ROOT'):
            return {}
        self._validate_runtime_paths()
        marker_dir = Path(self._errors_dir)
        marker_dir.mkdir(parents=True, exist_ok=True)
        (Path(self._runtime_context['RS_RUNTIME_ROOT']) / 'models').mkdir(exist_ok=True)
        hashes = {}
        for name in ('ErrorWriter.bat', 'ErrorWriterLaunch.vbs'):
            source, target = Path(ERROR_HELPERS_DIR) / name, marker_dir / name
            data = source.read_bytes()
            expected = hashlib.sha256(data).hexdigest()
            if target.is_symlink() or target.is_junction() or (target.exists() and target.stat().st_nlink != 1):
                raise ValueError(f'Refusing redirected ErrorWriter helper: {target}')
            if not target.exists():
                with target.open('xb') as out:
                    out.write(data)
                    out.flush()
                    os.fsync(out.fileno())
            if (hashlib.sha256(target.read_bytes()).hexdigest() != expected
                    or hashlib.sha256(source.read_bytes()).hexdigest() != expected):
                raise ValueError(f'ErrorWriter helper drift; select a new attempt directory: {target}')
            hashes[name] = expected
        return hashes

    # ------------------------------------------------------------------
    # Executable discovery
    # ------------------------------------------------------------------

    def find_executable(self) -> str:
        """Resolve the pinned selection and validate the actual RS 2.2 binary.

        An explicit but invalid selection fails closed, never falls back to an
        unrelated install. Resource/hash validation is reused from installation
        preflight; unchanged file identity is cached to avoid hashing a large exe
        on every monitor poll. Recreate the CLI after changing approved settings.
        """
        from modules.rs_installation import validate_installation

        explicit = (self._executable_override if self._executable_override is not None
                    else self._configured_executable)
        candidates = [explicit] if explicit is not None else EXECUTABLE_CANDIDATES
        diagnostics = []
        for candidate in candidates:
            if (not isinstance(candidate, str) or not os.path.isabs(candidate)
                    or os.path.basename(candidate).casefold() != 'realityscan.exe'):
                diagnostics.append(f'Expected an absolute RealityScan.exe path: {candidate!r}')
                continue
            path = os.path.realpath(candidate)
            try:
                stat = os.stat(path)
            except OSError as exc:
                diagnostics.append(str(exc))
                continue
            identity = (os.path.normcase(path), stat.st_dev, stat.st_ino,
                        stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
            if self._validated_executable == identity:
                return path
            report = validate_installation(os.path.dirname(path))
            if report['valid'] and os.path.normcase(os.path.realpath(report['executable'])) == os.path.normcase(path):
                after = os.stat(path)
                if identity[1:] != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                    raise RuntimeError('RealityScan executable changed during validation; retry after the installation is stable.')
                self._validated_executable = identity
                return path
            diagnostics.extend(report['diagnostics'])
        raise FileNotFoundError('Supported RealityScan 2.2 executable unavailable. '
                                'Select RS_EXECUTABLE explicitly. ' + '; '.join(diagnostics))

    # ------------------------------------------------------------------
    # Instance status (via RealityScan's own -getStatus)
    # ------------------------------------------------------------------

    def is_instance_running(self) -> bool:
        # Unknown/query failure is occupied, never permission to boot or release.
        return self.get_instance_status(self.instance_name) is not None

    @staticmethod
    def _process_inventory() -> list[dict]:
        """Complete Windows process census; no application commands or signals."""
        if os.name != 'nt':
            raise OSError('Windows process census is required to establish instance absence')
        command = ("$ErrorActionPreference='Stop'; "
                   "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); "
                   "@(Get-CimInstance Win32_Process -ErrorAction Stop | "
                   "Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine,Name) | "
                   "ConvertTo-Json -Depth 3 -Compress")
        result = subprocess.run(
            [os.path.join(os.environ['SystemRoot'], 'System32', 'WindowsPowerShell', 'v1.0',
                          'powershell.exe'), '-NoProfile', '-NonInteractive', '-Command', command],
            capture_output=True, text=True, encoding='utf-8', errors='strict',
            timeout=STATUS_CALL_TIMEOUT_SECONDS, creationflags=_NO_WINDOW)
        if result.returncode != 0:
            raise OSError('Windows process census failed')
        rows = json.loads(result.stdout)
        if not isinstance(rows, list) or not rows or any(
                not isinstance(row, dict) or type(row.get('ProcessId')) is not int
                or type(row.get('ParentProcessId')) is not int
                or not isinstance(row.get('Name'), str) for row in rows):
            raise OSError('Windows process census is incomplete or malformed')
        return rows

    @staticmethod
    def _process_argv(row) -> list[str]:
        """Use Windows' argument parser, never shell interpretation of process text."""
        command = row.get('CommandLine')
        if not isinstance(command, str) or not command.strip():
            raise OSError('Process command line is unavailable')
        if os.name != 'nt':
            raise OSError('Windows argument inspection is unavailable')
        import ctypes
        from ctypes import wintypes
        shell = ctypes.WinDLL('shell32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        shell.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
        shell.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        count = ctypes.c_int()
        pointer = shell.CommandLineToArgvW(command, ctypes.byref(count))
        if not pointer:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return [pointer[i] for i in range(count.value)]
        finally:
            kernel.LocalFree(pointer)

    def _instance_absent(self, instance: str) -> bool:
        """Independent negative evidence; unreadable or unnamed RS blocks release."""
        try:
            for row in self._process_inventory():
                if row['Name'].casefold() != 'realityscan.exe':
                    continue
                argv = self._process_argv(row)
                # Transient read-only status helpers are not persistent instances.
                if len(argv) == 3 and argv[1].casefold() == '-getstatus':
                    continue
                names = [argv[i + 1] for i, arg in enumerate(argv[:-1])
                         if arg.casefold() == '-setinstancename']
                if len(names) != 1 or instance == '*' or names[0].casefold() == instance.casefold():
                    return False
            return True
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
            return False

    def wait_for_instance_shutdown(self, timeout: float = None) -> bool:
        """Block until the instance is gone. Returns False on timeout —
        callers must treat that as 'do not start the next workflow'."""
        if timeout is None:
            timeout = float(self.settings.get('realityscan', 'shutdown_timeout', SHUTDOWN_VERIFY_TIMEOUT_SECONDS))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.is_instance_running():
                return True
            time.sleep(PROGRESS_POLL_SECONDS)
        return False

    def shutdown_instance(self) -> bool:
        """Only quit a retained boot workflow after its .bat has stopped.

        Never infer ownership from the configured name or a stale PID marker.
        Normal completion remains the responsibility of the existing .bat.
        """
        if not self.is_instance_running():
            return True
        with self._runtime_guard:
            owned = next((run for run in self._runs.values()
                          if not run.attach and run.instance == self.instance_name
                          and run.process is not None and run.process.poll() is not None
                          and run.abort_final_sent and run.idle_revision is not None
                          and self._boot_proven(run)), None)
        if owned is None:
            raise RuntimeError('Refusing to quit without owned boot and queue-idle evidence')
        if not self._owned_control(owned, '-quit'):
            return False
        return self.wait_for_instance_shutdown()

    @staticmethod
    def _parse_status_line(raw: str) -> dict:
        """Parse a -getStatus live line into a dict.

        The line looks like::

            id:save progress:100.0% runtime:5 endEstimation:0 rev:147 lastError:0

        ``rev``/``lastError``/``runtime``/``endEstimation`` are returned as
        ints when they parse (``lastError`` is a SIGNED 32-bit decimal, e.g.
        -2113863583 for a failed -save); everything else stays a string
        (``progress`` keeps its literal ``%``). The unparsed line is kept
        under ``raw``.
        """
        status = {'raw': raw}
        for token in raw.split():
            key, sep, value = token.partition(':')
            if not sep or not key:
                continue
            if key in ('rev', 'lastError', 'runtime', 'endEstimation'):
                try:
                    status[key] = int(value)
                    continue
                except ValueError:
                    pass
            status[key] = value
        return status

    def get_instance_status(self, instance: str = None) -> dict | None:
        """Snapshot ``<exe> -getStatus <instance>`` as a parsed dict.

        Returns None only for a negative CLI response PLUS a complete process
        census excluding this instance. A failed query alone is unconfirmed, not
        absence. Returns an ``unconfirmed`` dict for all ambiguous failures,
        the dict from :meth:`_parse_status_line` when it does, and
        ``{'raw': '', 'timeout': True}`` when -getStatus hangs (instance
        exists but is unresponsive - same conservative reading as
        :meth:`is_instance_running`).

        stdout goes to a temporary FILE, never a pipe (WINDOWS TRAP recorded
        2026-08-07): startRealityScan.bat launches the GUI-subsystem
        instance via ``start ""`` and that child INHERITS any captured
        stdout/stderr pipe handles, keeping the pipe alive for the
        instance's whole life - so pipe capture anywhere near a boot path
        can block readers indefinitely. A file handle detaches cleanly, and
        using it here too keeps every -getStatus capture on the safe
        pattern.
        """
        exe = self.find_executable()
        instance = instance or self.instance_name
        fd, tmp_path = tempfile.mkstemp(prefix='rs_status_', suffix='.txt')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as out:
                try:
                    result = subprocess.run(
                        [exe, '-getStatus', instance],
                        stdout=out, stderr=subprocess.DEVNULL,
                        timeout=STATUS_CALL_TIMEOUT_SECONDS,
                        creationflags=_NO_WINDOW,
                    )
                except (OSError, subprocess.TimeoutExpired) as exc:
                    return {'raw': '', 'unconfirmed': True,
                            'timeout': isinstance(exc, subprocess.TimeoutExpired), 'reason': str(exc)}
            if result.returncode != 0:
                if self._instance_absent(instance):
                    return None
                return {'raw': '', 'unconfirmed': True, 'return_code': result.returncode}
            with open(tmp_path, 'r', encoding='utf-8', errors='replace') as f:
                raw = f.read().strip()
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return self._parse_status_line(raw) if raw else {'raw': '', 'unconfirmed': True}

    # ------------------------------------------------------------------
    # Locking (one orchestrator per instance name)
    # ------------------------------------------------------------------

    def _lock_path(self, instance: str = None) -> str:
        # '*' (attach mode's "first available instance") is not a legal
        # filename character; all wildcard attaches share one lock, which is
        # the right scope anyway - '*' is ambiguous by nature, so two
        # concurrent wildcard drivers could race for the same instance.
        inst = (instance or self.instance_name).replace('*', 'WILDCARD')
        return os.path.join(self._errors_dir, f'{inst}.lock')

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if os.name == 'nt':
            # CSV output and an exact PID-field comparison: a plain
            # substring check would match PID 123 against 1234 (or a
            # memory column) and treat a stale lock as live.
            result = subprocess.run(
                ['tasklist', '/FI', f'PID eq {pid}', '/NH', '/FO', 'CSV'],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                creationflags=_NO_WINDOW
            )
            for row in csv.reader(io.StringIO(result.stdout)):
                if len(row) >= 2 and row[1].strip() == str(pid):
                    return True
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    @staticmethod
    def _validate_instance(instance: str, *, attach: bool = False):
        if attach and instance == '*':
            return
        if (not re.fullmatch(r'[A-Za-z0-9_.-]+', instance)
                or instance in ('.', '..')):
            raise RuntimeError(
                f'Refusing to BOOT/control instance {instance!r}: use a plain '
                'instance token. Wildcards require attach mode; booting one '
                'could apply -newScene -deleteAutosave to an unrelated scene.')

    @staticmethod
    def _lease_stem(instance):
        return hashlib.sha256(instance.casefold().encode('utf-8')).hexdigest()

    def _acquire_lock(self, instance: str = None, *, token: str = None) -> None:
        inst = instance or self.instance_name
        self._validate_instance(inst, attach=True)
        key = inst.casefold()
        with self._runtime_guard:
            if key in self._leases:
                raise RuntimeError(f'Instance {inst} already has an owned workflow')
            os.makedirs(LOCKS_DIR, exist_ok=True)
            self._validate_runtime_paths()
            os.makedirs(self._errors_dir, exist_ok=True)
            gate = anchor = None
            journal = os.path.join(LOCKS_DIR, self._lease_stem(inst) + '.owner.json')
            created = False
            try:
                # Named instances share this gate. A wildcard takes it
                # exclusively, excluding ALL named instances in all checkouts.
                gate = _OSLock(os.path.join(LOCKS_DIR, 'all.lock'), shared=inst != '*')
                anchor = _OSLock(os.path.join(LOCKS_DIR, self._lease_stem(inst) + '.lock'))
                wildcard = self._lease_stem('*') + '.owner.json'
                unresolved = ([name for name in os.listdir(LOCKS_DIR)
                               if name.endswith('.owner.json')] if inst == '*'
                              else [name for name in (os.path.basename(journal), wildcard)
                                    if os.path.exists(os.path.join(LOCKS_DIR, name))])
                if unresolved:
                    raise RuntimeError(
                        f'Instance {inst} has unreconciled ownership in {LOCKS_DIR}: '
                        f'{unresolved}. A dead driver does not prove its workflow stopped.')
                lease = _Lease(token or uuid.uuid4().hex, gate, anchor,
                               journal, self._lock_path(inst))
                # Publish only while the OS locks are held; an empty/partial
                # record can never be mistaken for permission to take over.
                with open(journal, 'x', encoding='utf-8') as out:
                    created = True
                    json.dump({'token': lease.token, 'pid': os.getpid(),
                               'instance': inst}, out)
                    out.flush()
                    os.fsync(out.fileno())
                with open(lease.marker, 'w', encoding='ascii') as out:
                    out.write(str(os.getpid()))
                self._leases[key] = lease
            except BaseException as exc:
                if created:
                    try:
                        os.remove(journal)
                    except OSError:
                        pass  # An unresolved journal refuses future takeover.
                if anchor is not None:
                    anchor.close()
                if gate is not None:
                    gate.close()
                if isinstance(exc, OSError):
                    raise RuntimeError(f'Cannot acquire RealityScan ownership for {inst}: {exc}') from exc
                raise

    def _release_lock(self, instance: str = None, *, token: str = None) -> bool:
        key = (instance or self.instance_name).casefold()
        with self._runtime_guard:
            lease = self._leases.get(key)
            if (lease is None or lease.retained or
                    (token is not None and lease.token != token)):
                return False
            try:
                with open(lease.journal, encoding='utf-8') as src:
                    owned = json.load(src).get('token') == lease.token
                if not owned:
                    return False
                os.remove(lease.journal)
                try:
                    with open(lease.marker, encoding='ascii') as src:
                        marker_owned = src.read().strip() == str(os.getpid())
                    if marker_owned:
                        os.remove(lease.marker)
                except OSError:
                    pass
            except (OSError, ValueError):
                # Preserve the journal when ownership cannot be established.
                # Never delete a replacement owner's record.
                return False
            self._leases.pop(key)
            lease.anchor.close()
            lease.gate.close()
            return True

    # ------------------------------------------------------------------
    # Marker files written by the instance / ErrorWriter hook
    # ------------------------------------------------------------------

    # Marker files are namespaced per instance so parallel instances (e.g.
    # one per GPU) can never read each other's state.

    def _marker(self, kind: str, instance: str = None) -> str:
        # The wildcard instance ('*', attach mode) owns no marker files and
        # '*' is not a legal filename character; map it to a name no real
        # instance can have, so the monitor's isfile() checks simply miss
        # and every read degrades to ''.
        inst = (instance or self.instance_name).replace('*', 'WILDCARD')
        names = {
            'progress': f'progress_{inst}.txt',
            'errors': f'errors_{inst}.txt',
            'results': f'results_{inst}.log',
        }
        return os.path.join(self._errors_dir, names[kind])

    def _clear_markers(self) -> None:
        # -getStatus can report an instance gone a few seconds before its
        # process fully exits and releases the progress-file handle
        # (observed 2026-07-23: next workflow's marker clear raced the
        # teardown). Retry briefly (per file) before declaring the
        # instance alive.
        for kind in ('progress', 'errors', 'results'):
            deadline = time.monotonic() + 60
            path = self._marker(kind)
            while os.path.isfile(path):
                try:
                    os.remove(path)
                    break
                except OSError:
                    # Windows cannot delete a file another process holds
                    # open; give a shutting-down instance time to release
                    # it, then treat it as genuinely still running.
                    if time.monotonic() > deadline:
                        raise RuntimeError(
                            f'Cannot clear marker file {path} - it is still held '
                            f'open after 60s, most likely by a running RealityScan '
                            f'instance "{self.instance_name}". Shut it down before '
                            'starting a new workflow.'
                        )
                    time.sleep(2)

    def _read_marker(self, kind: str, instance: str = None) -> str:
        path = self._marker(kind, instance)
        if not os.path.isfile(path):
            return ''
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                return f.read().strip()
        except OSError:
            return ''

    # ------------------------------------------------------------------
    # Workflow execution
    # ------------------------------------------------------------------

    def _emit(self, run: _Run, kind: str, **data):
        run.sequence += 1
        event = RunEvent(run.run_id, run.sequence, kind, run.instance,
                         MappingProxyType(dict(data)), run.parent_run_id)
        if run.event_file:
            try:
                # One write while holding an OS lock also works for parallel
                # Windows stage children sharing this attempt's event stream.
                with self._event_writer(run.event_file) as out:
                    out.write(json.dumps(event.as_dict(), ensure_ascii=True) + '\n')
                    out.flush()
                    os.fsync(out.fileno())
            except OSError as exc:
                self.logger.error('Runtime event persistence failed: %s', exc)
        if run.observer is not None:
            try:
                run.observer(event)
            except KeyboardInterrupt:
                run.control.request_cancel('KeyboardInterrupt', mode='abort_current')
            except Exception as exc:
                self.logger.warning('Runtime observer failed: %s', exc)

    @staticmethod
    def _event_writer(path):
        from contextlib import contextmanager

        @contextmanager
        def writer():
            guard = None
            for _ in range(50):
                try:
                    guard = _OSLock(path + '.lock')
                    break
                except OSError:
                    time.sleep(0.01)
            if guard is None:
                raise OSError('runtime event stream is locked')
            try:
                with open(path, 'a', encoding='utf-8') as out:
                    yield out
            finally:
                guard.close()
        return writer()

    def _configure_channels(self, run: _Run):
        env = run.environment
        control, events = env.get('RS_CONTROL_FILE'), env.get('RS_EVENT_FILE')
        if not control and not events:
            return
        parent = env.get('RS_RUN_ID', '')
        root = os.path.realpath(env.get('RS_RUNTIME_ROOT', ''))
        if (not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', parent) or
                not env.get('RS_RUNTIME_ROOT') or
                not os.path.isabs(env.get('RS_RUNTIME_ROOT', '')) or
                os.path.normcase(os.path.basename(root)) != os.path.normcase(parent) or
                os.path.basename(os.path.dirname(root)).lower() != 'tmp' or
                os.path.basename(os.path.dirname(os.path.dirname(root))).lower() != 'proc'):
            raise ValueError('Runtime channels require RS_RUN_ID and RS_RUNTIME_ROOT=<project>/proc/tmp/<run_id>')
        assert_bat_safe([root], 'runtime control directory')
        for path in (control, events):
            if path and (not os.path.isabs(path) or
                         os.path.normcase(os.path.dirname(os.path.realpath(path))) != os.path.normcase(root)):
                raise ValueError('Runtime control/event file must be directly inside this attempt directory')
        if control and events and os.path.normcase(os.path.realpath(control)) == os.path.normcase(os.path.realpath(events)):
            raise ValueError('Control and event files must be distinct')
        os.makedirs(root, exist_ok=True)
        run.parent_run_id = parent
        run.control_file = os.path.realpath(control) if control else None
        run.event_file = os.path.realpath(events) if events else None
        run.abort_sentinel = os.path.join(root, f'abort_{run.run_id}.sentinel')

    def _poll_control(self, run: _Run):
        if run.startup_refused_file and os.path.exists(run.startup_refused_file):
            run.ownership_refused = True
        if run.control_file:
            try:
                with open(run.control_file, encoding='utf-8') as source:
                    raw = source.read(4097)
                if len(raw) > 4096:
                    raise ValueError('control request exceeds 4096 characters')
                request = json.loads(raw)
                if not isinstance(request, dict) or request.get('run_id') != run.parent_run_id:
                    raise ValueError('control request run_id does not match this attempt')
                mode = request.get('mode')
                if mode not in ('after_step', 'abort_current'):
                    raise ValueError('invalid control request mode')
                requested_at = request.get('requested_at')
                if isinstance(requested_at, str):
                    stamp = datetime.fromisoformat(requested_at.replace('Z', '+00:00'))
                    if stamp.tzinfo is None:
                        raise ValueError('requested_at must include a timezone')
                elif (isinstance(requested_at, bool) or not isinstance(requested_at, (int, float))
                      or not math.isfinite(requested_at) or requested_at <= 0):
                    raise ValueError('requested_at must be an ISO timestamp or positive epoch seconds')
                if mode == 'after_step':
                    if not run.file_after_step_requested:
                        run.file_after_step_requested = True
                        self._emit(run, 'cancel_requested', reason='control file',
                                   mode=mode, scope='stage')
                else:
                    run.control.request_cancel('control file', mode=mode)
                run.control_error = ''
            except FileNotFoundError:
                pass
            except (OSError, ValueError) as exc:
                message = str(exc)
                if message != run.control_error:
                    run.control_error = message
                    self._emit(run, 'control_rejected', reason=message)
        if run.control.cancellation_requested and run.notified_mode != run.control.mode:
            run.notified_mode = run.control.mode
            self._emit(run, 'cancel_requested', reason=run.control.reason, mode=run.control.mode)

    def _owned_control(self, run: _Run, command: str, *, evidence: dict | None = None) -> bool:
        if command not in ('-abortInstance', '-quit', '-waitCompleted'):
            raise ValueError('Unsupported runtime control command')
        lease = self._leases.get(run.instance.casefold())
        if (run.attach or lease is None or lease.token != run.run_id or run.process is None
                or not self._boot_proven(run)):
            raise RuntimeError('Refusing an instance control command without owned boot provenance')
        try:
            return self._send_instance_control(run.environment['RS_EXECUTABLE'], run.instance,
                                               command, evidence=evidence)
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._emit(run, 'abort_unconfirmed', reason=str(exc))
            return False

    @staticmethod
    def _send_instance_control(executable: str, instance: str, command: str,
                               *, evidence: dict | None = None) -> bool:
        """Single control dispatch shared by live ownership and reviewed recovery."""
        if command not in ('-abortInstance', '-quit', '-waitCompleted'):
            raise ValueError('Unsupported runtime control command')
        argv = [executable] + (['-delegateTo', instance, '-quit'] if command == '-quit'
                               else [command, instance])
        # A file avoids the inherited-pipe deadlock of persistent GUI instances.
        # Capture only for explicit diagnosis; existing callers retain bool API.
        with tempfile.TemporaryFile() as output:
            started = time.monotonic()
            try:
                result = subprocess.run(
                    argv, stdout=output if evidence is not None else subprocess.DEVNULL,
                    stderr=subprocess.STDOUT if evidence is not None else subprocess.DEVNULL,
                    timeout=STATUS_CALL_TIMEOUT_SECONDS, creationflags=_NO_WINDOW)
                if evidence is not None:
                    evidence.update(return_code=result.returncode,
                                    return_code_hex=f'0x{result.returncode & 0xffffffff:08x}')
                return result.returncode == 0
            except (OSError, subprocess.TimeoutExpired) as exc:
                if evidence is not None:
                    evidence.update(return_code=None, reason=str(exc),
                                    timed_out=isinstance(exc, subprocess.TimeoutExpired))
                raise
            finally:
                if evidence is not None:
                    length = output.tell()
                    output.seek(max(0, length - 65536))
                    raw = output.read()
                    encoding = ('utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else
                                'utf-16-le' if b'\0' in raw[:128] else 'utf-8-sig')
                    evidence.update(command=command, instance=instance, elapsed_seconds=time.monotonic() - started,
                                    output=raw.decode(encoding, errors='replace'), output_bytes=length,
                                    output_truncated=length > 65536)

    @staticmethod
    def _idle_revision(status, *, abort_acknowledged: bool) -> int | None:
        """Post-abort idle control, not an operation-completion percentage.

        Official delegation docs define abort + waitCompleted. The sentinel is
        empirical for 2.2.0.119430 (testing/NA167_SESSION_NOTES.md section 3.1),
        corroborated by the controlled 2026-09-11 probe. Never accept it alone.
        Sticky lastError describes the prior failure, not current queue activity.
        The same probe returned waitCompleted exit 1 before and after identical
        idle observations. Its undocumented exit code is diagnostic, not a gate;
        callers still require acknowledged abort, stopped dispatch, ownership
        revalidation and TWO matching revisions before issuing quit.
        """
        if (not abort_acknowledged or not isinstance(status, dict)
                or status.get('timeout') or status.get('unconfirmed')
                or str(status.get('id', '')).casefold() != '0xffffffff'
                or type(status.get('rev')) is not int or status['rev'] < 0):
            return None
        try:
            progress = float(str(status.get('progress', '')).removesuffix('%'))
            estimate = float(str(status.get('endEstimation', '')).removesuffix('sec'))
            if progress == 0.0 and estimate == 0.0:
                return status['rev']
        except (ValueError, TypeError):
            pass
        return None

    @staticmethod
    def _record_recovery(proposal: dict, kind: str, **data):
        path = Path(proposal['log_dir']) / f'recovery_{proposal["run_id"]}.jsonl'
        if path.is_symlink() or path.is_junction() or (path.exists() and path.stat().st_nlink != 1):
            raise ValueError('Refusing redirected recovery evidence file')
        event = dict(run_id=proposal['run_id'], recovery_id=proposal['recovery_id'],
                     kind=kind, observed_at=time.time(), data=data)
        with path.open('a', encoding='utf-8') as out:
            out.write(json.dumps(event, ensure_ascii=True) + '\n')
            out.flush()
            os.fsync(out.fileno())

    def _begin_failed_cleanup(self, run: _Run):
        if (not run.attach and not run.ownership_refused and run.process is not None
                and run.process.poll() is not None and not run.control.cancellation_requested
                and (run.process.returncode != 0 or run.monitor_error
                     or self._read_marker('errors', run.instance)) and self._boot_proven(run)):
            run.failure_cleanup = True
            run.control.request_cancel('Owned workflow failed; cleaning up', mode='abort_current')
            self._emit(run, 'failure_cleanup_requested', return_code=run.process.returncode)

    def inspect_owned_recovery(self, run_id: str, log_dir: str, *, instance_pid: int) -> dict:
        """Read-only proposal for an explicitly approved abort of a stranded owner.

        No lease is acquired/adopted. The original Python must remain alive with
        its original journal; its batch must be absent. Windows creation identity,
        named-instance command line and boot receipt bind the recovery target.
        """
        from modules.project_runtime import _windows_process_snapshot

        self._validate_instance(self.instance_name)
        if not re.fullmatch(r'[0-9a-f]{32}', run_id) or type(instance_pid) is not int or instance_pid <= 0:
            raise ValueError('Expected exact workflow ID and instance PID')
        directory = Path(log_dir)
        if not directory.is_absolute() or not directory.is_dir():
            raise ValueError('Recovery requires an existing absolute log directory')
        if not any(p.name.casefold() == 'tmp' and p.parent.name.casefold() == 'proc'
                   for p in (directory, *directory.parents)):
            raise ValueError('Recovery logs must be under project/proc/tmp')
        sentinel = directory / f'abort_{run_id}.sentinel'
        boot = Path(str(sentinel) + '.boot-owned')
        journal = Path(LOCKS_DIR) / (self._lease_stem(self.instance_name) + '.owner.json')
        for path in (sentinel, boot, journal, *directory.parents, directory):
            if path.is_symlink() or path.is_junction():
                raise ValueError(f'Recovery refuses redirected paths: {path}')
            if path.is_file() and path.stat().st_nlink != 1:
                raise ValueError(f'Recovery refuses hardlinked evidence: {path}')
        raw = journal.read_bytes()
        owner = json.loads(raw)
        if (not isinstance(owner, dict) or owner.get('token') != run_id
                or owner.get('instance') != self.instance_name
                or type(owner.get('pid')) is not int or owner['pid'] <= 0):
            raise ValueError('Owner journal does not match the selected workflow')
        if boot.read_text(encoding='ascii').strip() != run_id:
            raise ValueError('Boot receipt does not match workflow')
        if Path(str(sentinel) + '.startup-refused').exists():
            raise ValueError('Startup refused ownership; recovery is forbidden')
        if sentinel.exists() and sentinel.read_text(encoding='ascii').strip() != run_id:
            raise ValueError('Existing abort sentinel belongs to another workflow')
        rows = self._process_inventory()
        selected = [row for row in rows if row['ProcessId'] == instance_pid]
        if len(selected) != 1:
            raise ValueError('Selected instance process is not present')
        app = selected[0]
        argv = self._process_argv(app)
        names = [argv[i + 1] for i, arg in enumerate(argv[:-1])
                 if arg.casefold() == '-setinstancename']
        if names != [self.instance_name]:
            raise ValueError('Selected PID does not carry the exact instance name')
        workflow_pid = app['ParentProcessId']
        if workflow_pid <= 0 or any(row['ProcessId'] == workflow_pid for row in rows):
            raise ValueError('Launching workflow still exists or cannot be identified; refuse external recovery')
        for row in rows:
            if row['ProcessId'] != instance_pid and row['Name'].casefold() == 'realityscan.exe':
                other = self._process_argv(row)
                named = [other[i + 1] for i, arg in enumerate(other[:-1])
                         if arg.casefold() == '-setinstancename']
                if not named and not (len(other) == 3 and other[1].casefold() == '-getstatus'):
                    raise ValueError('Another live RealityScan command could still be dispatching')
                if any(arg.casefold() == '-setinstancename' and i + 1 < len(other)
                       and other[i + 1].casefold() == self.instance_name.casefold()
                       for i, arg in enumerate(other)):
                    raise ValueError('More than one process claims the instance name')
            if row['ParentProcessId'] == owner['pid']:
                child_args = self._process_argv(row)
                if (row['Name'].casefold() != 'realityscan.exe' or len(child_args) != 3
                        or child_args[1:] != ['-getStatus', self.instance_name]):
                    raise ValueError('Owner still has a child other than its read-only status query')
        driver = _windows_process_snapshot(owner['pid'])
        instance = _windows_process_snapshot(instance_pid)
        if driver['status'] != 'running' or instance['status'] != 'running':
            raise ValueError('Original owner and selected instance must both remain running')
        executable = self.find_executable()
        if os.path.normcase(instance['identity']['image_path']) != os.path.normcase(executable):
            raise ValueError('Selected process uses a different executable')
        # Receipt is emitted immediately after start. A later replacement PID
        # cannot be approved using this old receipt, even under the same name.
        boot_time = boot.stat().st_mtime_ns // 100 + 116444736000000000
        owner_time = journal.stat().st_mtime_ns // 100 + 116444736000000000
        if (driver['identity']['created_filetime'] > owner_time
                or abs(instance['identity']['created_filetime'] - boot_time) > 5 * 10_000_000
                or owner_time > boot_time):
            raise ValueError('Process creation times do not match original ownership evidence')
        if journal.read_bytes() != raw or boot.read_text(encoding='ascii').strip() != run_id:
            raise ValueError('Ownership evidence changed during inspection')
        proposal = dict(schema=1, run_id=run_id, instance=self.instance_name,
                        log_dir=str(directory), sentinel=str(sentinel), executable=executable,
                        owner=driver['identity'], process=instance['identity'], workflow_pid=workflow_pid,
                        journal_sha256=hashlib.sha256(raw).hexdigest())
        proposal['recovery_id'] = hashlib.sha256(json.dumps(proposal, sort_keys=True).encode()).hexdigest()
        return proposal

    def recover_owned_failure(self, proposal: dict, *, approved_recovery_id: str) -> dict:
        """Explicit bounded abort/idle/quit operation; original owner retains lease.

        Revalidate before both mutating commands. Never signal Python, construct
        a replacement lease, erase a journal or claim another owner's release.
        An unconfirmed return leaves the original monitor alive; callers may
        retry the reviewed proposal while its process identities still match.
        """
        from modules.project_runtime import inspect_owned_process

        if not approved_recovery_id or proposal.get('recovery_id') != approved_recovery_id:
            raise ValueError('Explicit approved recovery ID is required')

        def validate():
            current = self.inspect_owned_recovery(proposal['run_id'], proposal['log_dir'],
                                                  instance_pid=proposal['process']['pid'])
            if current != proposal:
                raise ValueError('Recovery evidence changed; inspect and approve again')

        validate()
        gate = _OSLock(os.path.join(proposal['log_dir'], f'recovery_{proposal["run_id"]}.lock'))
        report = dict(recovery_id=approved_recovery_id, instance_absent=False,
                      original_owner_releases_ownership=True, status='unconfirmed', observations=[],
                      evidence_path=os.path.join(proposal['log_dir'], f'recovery_{proposal["run_id"]}.jsonl'))
        try:
            validate()
            sentinel = Path(proposal['sentinel'])
            if not sentinel.exists():
                with sentinel.open('x', encoding='ascii') as out:
                    out.write(proposal['run_id'] + '\n')
                    out.flush()
                    os.fsync(out.fileno())
            self._record_recovery(proposal, 'abort_requested')
            abort_acknowledged = self._send_instance_control(
                proposal['executable'], proposal['instance'], '-abortInstance')
            if not abort_acknowledged:
                return report | {'reason': 'Abort command was not acknowledged'}
            self._record_recovery(proposal, 'abort_acknowledged')
            barrier_evidence = {}
            report['barrier'] = barrier_evidence
            try:
                barrier = self._send_instance_control(proposal['executable'], proposal['instance'],
                                                      '-waitCompleted', evidence=barrier_evidence)
            except (OSError, subprocess.TimeoutExpired):
                barrier = False  # The exact diagnostic remains in barrier_evidence.
            self._record_recovery(proposal, 'wait_completed', client_succeeded=barrier,
                                  diagnostic_only=True, client=barrier_evidence)
            revision = None
            for _ in range(3):
                time.sleep(PROGRESS_POLL_SECONDS)
                status = self.get_instance_status(proposal['instance'])
                report['observations'].append(status)
                self._record_recovery(proposal, 'post_barrier_status', status=status)
                if status is None:
                    break
                observed = self._idle_revision(status, abort_acknowledged=abort_acknowledged)
                if observed is None:
                    revision = None
                    continue
                if revision == observed:
                    validate()
                    self._record_recovery(proposal, 'quit_requested', stable_revision=observed)
                    if not self._send_instance_control(proposal['executable'], proposal['instance'], '-quit'):
                        return report | {'reason': 'Quit command was not acknowledged'}
                    break
                revision = observed
            else:
                return report | {'reason': 'Stable queue idle is not yet confirmed; original owner retained'}
            time.sleep(PROGRESS_POLL_SECONDS)
            process = inspect_owned_process(proposal['process'])
            absent = (process['confirmed_not_running'] and self.get_instance_status(proposal['instance']) is None)
            self._record_recovery(proposal, 'reconciled', instance_absent=absent, process=process)
            return report | {'instance_absent': absent, 'status': 'instance_absent' if absent else 'unconfirmed',
                             'process': process}
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._record_recovery(proposal, 'recovery_unconfirmed', reason=str(exc))
            return report | {'reason': str(exc)}
        finally:
            gate.close()

    def diagnose_owned_barrier(self, proposal: dict) -> dict:
        """Measure status/waitCompleted/status without abort, quit or ownership changes.

        The wait client's exit code is evidence, not a queue-idle interpretation.
        Only the bounded wait client runs; the persistent RS instance is never
        terminated on timeout. Caller can save the returned JSON as well as the
        durable recovery observation stream recorded here.
        """
        current = self.inspect_owned_recovery(proposal['run_id'], proposal['log_dir'],
                                              instance_pid=proposal['process']['pid'])
        if current != proposal:
            raise ValueError('Recovery evidence changed; inspect again before diagnosis')
        report = {'recovery_id': proposal['recovery_id'], 'barrier': {}, 'after': [],
                  'interpretation': 'diagnostic_only', 'mutating_commands_sent': False}
        report['before'] = self.get_instance_status(proposal['instance'])
        self._record_recovery(proposal, 'barrier_diagnostic_before', status=report['before'])
        try:
            self._send_instance_control(proposal['executable'], proposal['instance'], '-waitCompleted',
                                        evidence=report['barrier'])
        except (OSError, subprocess.TimeoutExpired):
            pass  # Exact error/timeout retained by the canonical command helper.
        self._record_recovery(proposal, 'barrier_diagnostic_client', client=report['barrier'])
        for _ in range(2):
            time.sleep(PROGRESS_POLL_SECONDS)
            status = self.get_instance_status(proposal['instance'])
            report['after'].append(status)
            self._record_recovery(proposal, 'barrier_diagnostic_after', status=status)
        return report

    @staticmethod
    def _boot_proven(run: _Run) -> bool:
        if run.startup_refused_file and os.path.exists(run.startup_refused_file):
            run.ownership_refused = True
            return False
        try:
            with open(run.boot_owned_file, encoding='ascii') as src:
                return src.read(128).strip() == run.run_id
        except (OSError, TypeError):
            return False

    def _advance_abort(self, run: _Run):
        if not run.control.cancellation_requested or run.control.mode != 'abort_current':
            return
        if run.attach:
            if not run.abort_refused:
                run.abort_refused = True
                self._emit(run, 'abort_refused', reason='Attached instance ownership is unknown; waiting for workflow completion')
            return
        if not run.abort_sentinel:
            raise RuntimeError('Owned abort requires a validated sentinel path')
        if not os.path.exists(run.abort_sentinel):
            with open(run.abort_sentinel, 'x', encoding='ascii') as out:
                out.write(run.run_id + '\n')
                out.flush()
                os.fsync(out.fileno())
            self._emit(run, 'dispatch_stopped', sentinel=run.abort_sentinel)
        if not self._boot_proven(run):
            if run.process.poll() is not None:
                if run.ownership_refused or self.get_instance_status(run.instance) is None:
                    run.abort_quiescent = True
            return
        if (run.failure_cleanup and run.process.poll() is not None
                and self.get_instance_status(run.instance) is None):
            run.abort_quiescent = True
            return
        # The first abort releases the .bat's active wait. Every subsequent
        # dispatch checks the sticky sentinel. A delegate already past its
        # guard may still be in flight, so repeat AFTER the .bat has exited.
        if not run.abort_initial_sent and not run.abort_final_sent:
            run.abort_initial_sent = self._owned_control(run, '-abortInstance')
        if run.process.poll() is None:
            return
        status = self.get_instance_status(run.instance)
        if status is None:
            run.abort_quiescent = True
            return
        if not run.abort_final_sent:
            run.abort_final_sent = self._owned_control(run, '-abortInstance')
            run.abort_wait_observed = False
            run.idle_revision = None
            return
        if not run.abort_wait_observed:
            evidence = {}
            succeeded = self._owned_control(run, '-waitCompleted', evidence=evidence)
            self._emit(run, 'abort_wait_completed', client_succeeded=succeeded,
                       diagnostic_only=True, client=evidence)
            run.abort_wait_observed = True
            run.idle_revision = None
            return
        revision = self._idle_revision(status, abort_acknowledged=run.abort_final_sent)
        self._emit(run, 'post_abort_status', status=status, idle_revision=revision)
        if revision is None:
            run.idle_revision = None
            return
        if run.idle_revision == revision and not run.shutdown_sent:
            run.shutdown_sent = self._owned_control(run, '-quit')
            self._emit(run, 'shutdown_requested', confirmed=run.shutdown_sent)
        run.idle_revision = revision

    def _wait_for_quiescence(self, run: _Run):
        """Keep the DRIVER alive, not just an in-process reference to its lease."""
        previous_error = ''
        while True:
            try:
                self._poll_control(run)
                self._begin_failed_cleanup(run)
                self._advance_abort(run)
                if run.process is not None and run.process.poll() is not None:
                    if run.ownership_refused:
                        quiet = True  # The guarded .bat never owned this instance.
                    elif run.control.mode == 'abort_current' and not run.attach:
                        quiet = run.abort_quiescent
                    else:
                        quiet = ((run.attach and run.process.returncode == 0) or
                                 self.get_instance_status(run.instance) is None)
                    if quiet:
                        self._leases[run.instance.casefold()].retained = False
                        return
            except KeyboardInterrupt:
                run.control.request_cancel('KeyboardInterrupt', mode='abort_current')
            except Exception as exc:
                if str(exc) != previous_error:
                    previous_error = str(exc)
                    self._emit(run, 'termination_unconfirmed', reason=previous_error)
            time.sleep(PROGRESS_POLL_SECONDS)

    def _complete_run(self, run: _Run):
        errors = self._read_marker('errors', run.instance) if not run.attach else ''
        if run.attach and run.process.returncode != 0:
            last_error = (self.get_instance_status(run.instance) or {}).get('lastError')
            errors = (f'lastError:{last_error}' if last_error not in (None, 0)
                      else f'workflow exited with code {run.process.returncode}')
        errors = run.monitor_error or errors
        if run.ownership_refused:
            errors = 'Startup ownership conflict: existing instance was not modified'
        run.status = ('failed' if run.failure_cleanup else
                      'cancelled' if run.control.cancellation_requested else
                      'done' if run.process.returncode == 0 and not errors else 'failed')
        self._snapshot_log(run, 'after')
        result = self._result(run, errors=errors)
        if not self._release_lock(run.instance, token=run.run_id):
            return self._retain_run(run, 'ownership_unconfirmed', 'ownership release could not be verified')
        with self._runtime_guard:
            self._runs.pop(run.run_id, None)
            with _RETAINED_GUARD:
                _RETAINED_RUNS.pop(run.run_id, None)
        self._emit(run, run.status, return_code=run.process.returncode,
                   ownership_retained=False)
        return result

    def _snapshot_log(self, run: _Run, phase: str):
        """Preserve a bounded tail of the shared RS log, with explicit provenance."""
        if not run.log_path:
            return
        local = run.environment.get('LOCALAPPDATA')
        if not local:
            return
        source = os.path.join(local, 'Temp', 'RealityScan.log')
        dest = os.path.join(os.path.dirname(run.log_path),
                            f'realityscan_{run.run_id}_{phase}.log')
        try:
            with open(source, 'rb') as src:
                size = os.fstat(src.fileno()).st_size
                src.seek(max(0, size - 8 * 1024 * 1024))
                with open(dest, 'xb') as out:
                    remaining = min(size, 8 * 1024 * 1024)
                    while remaining:
                        chunk = src.read(min(remaining, 64 * 1024))
                        if not chunk:
                            break
                        out.write(chunk)
                        remaining -= len(chunk)
            self._emit(run, 'log_snapshot', path=dest, source=source,
                       shared_global_log=True, tail_bytes=min(size, 8 * 1024 * 1024))
        except FileNotFoundError:
            pass
        except OSError as exc:
            self.logger.warning('Could not snapshot shared RealityScan log: %s', exc)

    def _result(self, run: _Run, *, errors: str = '', retained: bool = False):
        code = run.process.returncode if run.process is not None else None
        results = [line for line in self._read_marker('results', run.instance).splitlines()
                   if line.strip()] if run.process is not None else []
        return WorkflowResult(
            run.status == 'done', code, run.log_path, errors, results,
            time.monotonic() - run.started, run.run_id, run.status,
            run.control.cancellation_requested and not run.failure_cleanup, retained, run.resource_path)

    def _retain_run(self, run: _Run, status: str, errors: str):
        run.status = status
        with self._runtime_guard:
            lease = self._leases[run.instance.casefold()]
            if lease.token != run.run_id:
                raise RuntimeError('Cannot retain another workflow\'s ownership')
            lease.retained = True
            self._runs[run.run_id] = run
            with _RETAINED_GUARD:
                _RETAINED_RUNS[run.run_id] = (self, run)
        self._emit(run, status, reason=errors, ownership_retained=True)
        return self._result(run, errors=errors, retained=True)

    def reconcile_run(self, run_id: str) -> WorkflowResult:
        """Nonblocking reconciliation, on the SAME CLI object that ran the work.

        No signals or commands that mutate RS are sent. A booted instance must
        be absent; an attached workflow must have exited successfully or its
        instance must be absent. An interrupted launch without a child handle
        cannot be confirmed here. Foreign/unknown run IDs are refused.
        """
        with self._runtime_guard:
            run = self._runs[run_id]
            if run.monitoring:
                return self._result(run, errors='driver is still monitoring quiescence', retained=True)
            if run.process is None or run.process.poll() is None:
                return self._result(run, errors='workflow termination is unconfirmed', retained=True)
            quiescent = (run.attach and run.process.returncode == 0)
            if not quiescent:
                quiescent = self.get_instance_status(run.instance) is None
            if not quiescent:
                return self._result(run, errors='instance termination is unconfirmed', retained=True)
            errors = self._read_marker('errors', run.instance) if not run.attach else ''
            run.status = ('failed' if run.failure_cleanup else
                          'cancelled' if run.control.cancellation_requested else
                          'done' if run.process.returncode == 0 and not errors else 'failed')
            result = self._result(run, errors=errors)
            self._snapshot_log(run, 'reconciled')
            lease = self._leases[run.instance.casefold()]
            lease.retained = False
            if not self._release_lock(run.instance, token=run.run_id):
                lease.retained = True
                run.status = 'ownership_unconfirmed'
                return self._result(run, errors='ownership release could not be verified', retained=True)
            del self._runs[run_id]
            with _RETAINED_GUARD:
                _RETAINED_RUNS.pop(run_id, None)
            self._emit(run, run.status, return_code=run.process.returncode,
                       ownership_retained=False)
            return result

    def run_batch_script(self, script_name: str, args: list[str], log_dir: str,
                         display_output: bool = False, gpu_devices: str = None,
                         *, control: RunControl = None,
                         observer: Callable[[RunEvent], None] = None) -> WorkflowResult:
        """Run the existing .bat workflow with exclusive instance ownership.

        A pre-existing instance is NEVER quit or reset. Cancellation keeps the
        driver alive and ownership held until workflow/instance quiescence.
        Observer callbacks execute on the worker thread and must be nonblocking.
        """
        return self._run_workflow(script_name, args, log_dir, self.instance_name,
                                  False, display_output, gpu_devices, control, observer)

    def run_attach_script(self, script_name: str, args: list[str],
                          log_dir: str, instance: str = '*', *,
                          control: RunControl = None,
                          observer: Callable[[RunEvent], None] = None) -> WorkflowResult:
        """Drive an explicitly selected existing instance; never boot or quit it."""
        return self._run_workflow(script_name, args, log_dir, instance,
                                  True, False, None, control, observer)

    def _run_workflow(self, script_name, args, log_dir, instance, attach,
                      display_output, gpu_devices, control, observer):
        assert_bat_safe(args, script_name)
        self._validate_instance(instance, attach=attach)
        env = dict(os.environ)
        for key in ('RS_RUN_ID', 'RS_RUNTIME_ROOT', 'RS_ERRORS_DIR', 'RS_CONTROL_FILE', 'RS_EVENT_FILE'):
            env.pop(key, None)
        env.update(self._runtime_context)
        for key in ('RS_INSTANCE', 'RS_CACHE_DIR', 'RS_HEADLESS', 'RS_ABORT_SENTINEL',
                    'RS_REQUIRE_NEW_INSTANCE', 'RS_STARTUP_REFUSED',
                    'RS_STARTUP_REFUSED_FILE', 'RS_BOOT_OWNED_FILE', 'RS_WORKFLOW_ID'):
            env.pop(key, None)
        env.update(self._machine_env)
        env['RS_PYTHON'] = sys.executable
        # An existing instance's actual cache cannot be inferred from the
        # current caller's settings. Report it as unknown in attach mode.
        if attach:
            env.pop('RS_CACHE_DIR', None)
        else:
            env['RS_INSTANCE'] = instance
            devices = (gpu_devices if gpu_devices is not None else
                       self.settings.get('realityscan', 'gpu_devices'))
            if devices:
                env['RS_GPU_DEVICES'] = str(devices)
                env['CUDA_VISIBLE_DEVICES'] = str(devices)
        run = _Run(uuid.uuid4().hex, instance, attach, MappingProxyType(env),
                   control if control is not None else RunControl(), observer)
        self._configure_channels(run)
        self._emit(run, 'prepared')
        self._poll_control(run)
        if run.control.cancellation_requested:
            run.status = 'cancelled'
            self._emit(run, 'cancelled', launched=False, ownership_retained=False)
            return self._result(run)
        exe = self.find_executable()
        env['RS_EXECUTABLE'] = exe
        # Copy before freezing so the mapping has no mutable external backing.
        run.environment = MappingProxyType(dict(env))
        script_path = os.path.join(SCRIPTS_DIR, script_name)
        if not os.path.isfile(script_path):
            raise FileNotFoundError(f'Workflow script not found: {script_path}')
        self._acquire_lock(instance, token=run.run_id)
        try:
            if attach:
                status = self.get_instance_status(instance)
                # Unknown occupancy blocks boot, but is not proof that an
                # existing instance is reachable for attach dispatch.
                if (not isinstance(status, dict) or status.get('unconfirmed')
                        or status.get('timeout') or not isinstance(status.get('id'), str)
                        or not status['id'].strip()):
                    raise RuntimeError(f'No reachable RealityScan instance "{instance}". '
                                       'Attach mode never boots an instance.')
            elif self.is_instance_running():
                raise RuntimeError(
                    f'Refusing to BOOT: RealityScan instance "{instance}" already exists. '
                    'Its ownership is unknown; no -quit or reset was sent. '
                    'Reconcile the previous run or explicitly select attach mode.')
            helper_hashes = self._prepare_runtime_paths()
            if helper_hashes:
                self._emit(run, 'runtime_helpers_verified', errors_dir=self._errors_dir, sha256=helper_hashes)
            os.makedirs(log_dir, exist_ok=True)
            stamp = time.strftime('%Y-%m-%d_%H-%M-%S') + '_' + run.run_id
            run.log_path = os.path.join(log_dir, f'output_{stamp}.txt')
            run.resource_path = os.path.join(
                log_dir, f'resources_{os.path.splitext(os.path.basename(script_name))[0]}_{stamp}.csv')
            if run.abort_sentinel is None:
                run.abort_sentinel = os.path.abspath(os.path.join(log_dir, f'abort_{run.run_id}.sentinel'))
            assert_bat_safe([run.abort_sentinel], 'abort sentinel')
            env['RS_ABORT_SENTINEL'] = run.abort_sentinel
            if not attach:
                run.startup_refused_file = run.abort_sentinel + '.startup-refused'
                run.boot_owned_file = run.abort_sentinel + '.boot-owned'
                env['RS_REQUIRE_NEW_INSTANCE'] = '1'
                env['RS_STARTUP_REFUSED_FILE'] = run.startup_refused_file
                env['RS_BOOT_OWNED_FILE'] = run.boot_owned_file
                env['RS_WORKFLOW_ID'] = run.run_id
            run.environment = MappingProxyType(dict(env))
            self._snapshot_log(run, 'before')
            if not attach:
                self._clear_markers()
            elif instance == self.instance_name:
                # Preserve the existing own-marker exception, never progress
                # or another instance's markers. OS ownership excludes drivers.
                for kind in ('errors', 'results'):
                    path = self._marker(kind)
                    if os.path.isfile(path):
                        try:
                            os.remove(path)
                        except OSError:
                            try:
                                with open(path, 'w', encoding='utf-8'):
                                    pass
                            except OSError:
                                self.logger.warning('Could not clear stale own marker %s', path)
            self._poll_control(run)
            if run.startup_refused_file and os.path.exists(run.startup_refused_file):
                run.ownership_refused = True
            if run.control.cancellation_requested:
                run.status = 'cancelled'
                if not self._release_lock(instance, token=run.run_id):
                    return self._retain_run(run, 'ownership_unconfirmed',
                                            'ownership release could not be verified')
                self._emit(run, 'cancelled', launched=False, ownership_retained=False)
                return self._result(run)
            argv = [script_path] + ([instance] if attach else []) + list(args)
            flags = (subprocess.CREATE_NEW_CONSOLE if display_output else
                     subprocess.CREATE_NO_WINDOW) if os.name == 'nt' else 0
            options = dict(cwd=SCRIPTS_DIR, env=dict(run.environment), creationflags=flags)
            # FILE output avoids inherited-pipe deadlocks. A visible console
            # must retain all three standard handles to remain interactive.
            with open(run.log_path, 'x', encoding='utf-8', errors='replace') as output:
                if not display_output:
                    options.update(stdin=subprocess.DEVNULL, stdout=output,
                                   stderr=subprocess.STDOUT)
                else:
                    output.write('Workflow stdout is displayed in its own console.\n')
                run.launch_attempted = True
                run.process = subprocess.Popen(argv, **options)
                run.status = 'running'
                self._emit(run, 'running', pid=run.process.pid, log_path=run.log_path,
                           resource_path=run.resource_path,
                           cache_dir=run.environment.get('RS_CACHE_DIR'))
                self._monitor_until_exit(
                    run.process, run.resource_path, marker_instance=instance, run=run)
            self._poll_control(run)
            self._begin_failed_cleanup(run)
            if run.control.cancellation_requested:
                self._retain_run(run, 'cancel_unconfirmed', 'Waiting for confirmed quiescence')
                self._wait_for_quiescence(run)
            elif not attach and not run.ownership_refused and not self.wait_for_instance_shutdown():
                self._retain_run(run, 'shutdown_unconfirmed', 'instance did not shut down')
                self._wait_for_quiescence(run)
            return self._complete_run(run)
        except BaseException as exc:
            lease = self._leases.get(instance.casefold())
            if (lease is not None and lease.token == run.run_id and
                    (run.process is not None or
                     (run.launch_attempted and not isinstance(exc, OSError)))):
                if isinstance(exc, KeyboardInterrupt):
                    run.control.request_cancel('KeyboardInterrupt', mode='abort_current')
                else:
                    run.monitor_error = str(exc) or type(exc).__name__
                self._retain_run(run, 'cancel_unconfirmed' if run.control.cancellation_requested
                                 else 'monitor_unconfirmed', str(exc) or type(exc).__name__)
                if run.process is not None:
                    self._wait_for_quiescence(run)
                    return self._complete_run(run)
            raise
        finally:
            # Retained leases explicitly refuse release here. In particular,
            # KeyboardInterrupt and monitor failures never abandon a live child.
            self._release_lock(instance, token=run.run_id)
            run.monitoring = False

    def _monitor_until_exit(self, process: subprocess.Popen,
                            resource_csv: str = None,
                            marker_instance: str = None, *, run: _Run = None) -> bool:
        """Poll the workflow process, relaying progress.txt updates and
        warning on stalls. No overall timeout by design.

        When `resource_csv` is given, a CPU/memory sample is appended every
        RESOURCE_SAMPLE_SECONDS and flushed immediately. Flushing per sample
        is the point: when RealityScan dies it takes its own log with it (the
        next instance overwrites Temp\\RealityScan.log), so the trace across
        the crash has to be durable as it is written, not at close.
        """
        progress_path = self._marker('progress', marker_instance)
        last_progress_line = ''
        last_errors = ''
        last_activity = time.monotonic()
        stall_warned = False
        # Frozen-progress detection, orthogonal to the silence guard: this one
        # keys on the recovered completion fraction rather than on the progress
        # line changing. Owned here and handed to _monitor_loop so a single
        # workflow keeps one history across the whole run.
        progress_tracker = _ProgressTracker()
        low_memory_warned = False

        cpu = _CpuSampler()
        trace = None
        next_sample = 0.0
        started = time.monotonic()
        peak = {'cpu_pct': 0.0, 'commit_used_gb': 0.0, 'ram_avail_gb_min': None, 'disk_free_gb_min': None,
                'cache_free_gb_min': None}
        if resource_csv:
            try:
                trace = open(resource_csv, 'x', encoding='utf-8', newline='')
                trace.write('iso_time,elapsed_s,cpu_pct,ram_avail_gb,'
                            'ram_total_gb,mem_load_pct,commit_used_gb,'
                            'commit_total_gb,disk_free_gb,cache_free_gb,progress\n')
                trace.flush()
            except OSError as exc:
                self.logger.warning('Could not open resource trace %s: %s',
                                    resource_csv, exc)
                trace = None

        try:
            return self._monitor_loop(process, progress_path, last_progress_line,
                               last_errors, last_activity, stall_warned,
                               low_memory_warned, cpu, trace, next_sample,
                               started, peak, marker_instance,
                               progress_tracker, run)
        finally:
            if trace is not None:
                trace.close()
                self.logger.info(
                    'Resource peaks [%s]: CPU %.0f%%, commit used %.1f GB, '
                    'minimum available RAM %s, minimum free disk %s, minimum free CACHE disk %s. Trace: %s',
                    self.instance_name, peak['cpu_pct'], peak['commit_used_gb'],
                    'n/a' if peak['ram_avail_gb_min'] is None
                    else f"{peak['ram_avail_gb_min']:.1f} GB",
                    'n/a' if peak['disk_free_gb_min'] is None
                    else f"{peak['disk_free_gb_min']:.1f} GB",
                    'n/a' if peak['cache_free_gb_min'] is None
                    else f"{peak['cache_free_gb_min']:.1f} GB",
                    resource_csv)

    def _monitor_loop(self, process, progress_path, last_progress_line,
                      last_errors, last_activity, stall_warned,
                      low_memory_warned, cpu, trace, next_sample, started,
                      peak, marker_instance=None, progress_tracker=None,
                      run: _Run = None) -> bool:
        # Defaulted rather than required: attach mode and the tests call this
        # directly, and a monitor that raises NameError is strictly worse than
        # one that quietly builds its own tracker.
        if progress_tracker is None:
            progress_tracker = _ProgressTracker()
        progress_stall_warned = False
        generation = progress_tracker.generation
        instance = marker_instance or self.instance_name
        while process.poll() is None:
            if run is not None:
                self._poll_control(run)
                self._advance_abort(run)
            time.sleep(PROGRESS_POLL_SECONDS)

            if trace is not None:
                elapsed = time.monotonic() - started
                if elapsed >= next_sample:
                    next_sample = elapsed + RESOURCE_SAMPLE_SECONDS
                    self._sample_resources(trace, cpu, peak, elapsed,
                                           last_progress_line, run=run)

            # Near-OOM crawl detection (owner-observed): RealityScan slows
            # drastically without crashing or spilling to disk. Warn once
            # per workflow when available RAM gets low so a later stall/
            # #timeout can be attributed correctly.
            if not low_memory_warned:
                avail = _available_ram_gb()
                if avail is not None and avail < LOW_MEMORY_WARN_GB:
                    low_memory_warned = True
                    self.logger.warning(
                        'Available RAM is down to %.1f GB - RealityScan is '
                        'known to slow to a crawl near OOM without crashing; '
                        'treat upcoming stalls/#timeout as probable memory '
                        'pressure, not hangs.', avail)

            line = self._tail_line(progress_path)
            if line and line != last_progress_line:
                last_progress_line = line
                self.logger.info('RealityScan [%s]: %s', instance, line)
                # '#timeout'-tagged progress is RealityScan reporting a
                # stalled operation: the elapsed counter keeps ticking, so
                # treating those lines as activity muted the stall warning
                # for 6 h while -importComponent hung (2026-07-23).
                if not line.rstrip().endswith('#timeout'):
                    last_activity = time.monotonic()
                    stall_warned = False

                # FROZEN PROGRESS, independent of the silence guard above.
                # #timeout lines are fed in deliberately: during zone_2's
                # freeze they carried the same fraction as the #progress lines
                # around them, and excluding them would discard half the
                # evidence that nothing was moving.
                frozen_for = progress_tracker.update(line)
                if run is not None:
                    self._emit(run, 'progress', raw=line,
                               generation=progress_tracker.generation,
                               frozen_seconds=frozen_for)
                if progress_tracker.generation != generation or frozen_for is None:
                    if progress_stall_warned and run is not None:
                        self._emit(run, 'progress_recovered',
                                   generation=progress_tracker.generation)
                    progress_stall_warned = False
                generation = progress_tracker.generation
                if frozen_for is not None and not progress_stall_warned:
                    progress_stall_warned = True
                    parsed = parse_progress_line(line)
                    p = progress_tracker.recovered_fraction(parsed[2], parsed[3])
                    avail = _available_ram_gb()
                    self.logger.warning(
                        'RealityScan [%s] operation %s has made NO measurable '
                        'progress for %.0f s of its own elapsed clock: the '
                        'recovered completion fraction is still %.6f (window '
                        '%.0f s, epsilon %g). The displayed 2-decimal figure '
                        'and the changing elapsed/remaining numbers both keep '
                        'moving while the work does not, which is why the '
                        'silence-based stall warning cannot see this. Not '
                        'aborting automatically; check the operation and '
                        'available checkpoints. Available RAM: %s.',
                        instance, parsed[0], frozen_for, p,
                        progress_tracker.window, progress_tracker.epsilon,
                        'unknown' if avail is None else '%.1f GB' % avail)
                    if run is not None:
                        self._emit(run, 'progress_stalled', generation=generation,
                                   frozen_seconds=frozen_for)

            errors = self._read_marker('errors', marker_instance)
            if errors and errors != last_errors:
                # The batch script aborts itself on the errors marker; we just
                # make the failure visible immediately instead of at the end.
                last_errors = errors
                self.logger.error('RealityScan [%s] reported an error: %s', instance, errors)
                if run is not None:
                    self._emit(run, 'error', message=errors)

            if not stall_warned and time.monotonic() - last_activity > STALL_WARNING_SECONDS:
                stall_warned = True
                avail = _available_ram_gb()
                ram_note = ('' if avail is None
                            else f' Available RAM: {avail:.1f} GB.')
                if last_progress_line.rstrip().endswith('#timeout'):
                    self.logger.warning(
                        'RealityScan [%s] has been stuck in a #timeout state for '
                        'over %.1f hours - either a hung operation (observed with '
                        '-importComponent on a relocated .rsalign) or a near-OOM '
                        'crawl (owner-observed; RealityScan slows drastically '
                        'without crashing).%s Intervention is probably required.',
                        instance, STALL_WARNING_SECONDS / 3600, ram_note)
                else:
                    self.logger.warning(
                        'RealityScan [%s] has reported no progress for over %.1f hours. '
                        'Long silences are normal for very large datasets; check the '
                        'instance manually if this persists.%s',
                        instance, STALL_WARNING_SECONDS / 3600, ram_note)
                if run is not None:
                    self._emit(run, 'progress_silent', raw=last_progress_line)
        return True

    def _sample_resources(self, trace, cpu: '_CpuSampler', peak: dict,
                          elapsed: float, progress_line: str, *, run: _Run = None) -> None:
        """Append one CPU/memory row and update running peaks.

        Deliberately tolerant: a failed sample must never take down a
        multi-hour run, so a bad read is skipped rather than raised. The
        progress line is carried along so a spike can be attributed to the
        operation that was running.
        """
        mem = _memory_status()
        cpu_pct = cpu.percent()
        if mem is None:
            return
        # Free space on the drive this trace lives on - the drive holding
        # the project and its scratch data. RealityScan surfaces a full disk as
        # HRESULT 0x80070070 through the process hook, indistinguishable from
        # any other failure without this column: the hull model ran 143 min and
        # died on ERROR_DISK_FULL at the texture step while this very trace
        # recorded only CPU and RAM (2026-07-26).
        try:
            disk_free = shutil.disk_usage(
                os.path.dirname(trace.name) or '.').free / (1024 ** 3)
        except OSError:
            disk_free = None
        # ...and on the CACHE drive, which is a DIFFERENT disk and is the one
        # that actually killed the hull model three times. The column above
        # watched the project drive and read 773.9 GB free for a whole run
        # while this one hit zero (2026-07-26).
        cache_dir = (run.environment if run is not None else self._machine_env).get('RS_CACHE_DIR')
        cache_free = None
        if cache_dir:
            try:
                cache_free = shutil.disk_usage(cache_dir).free / (1024 ** 3)
            except OSError:
                cache_free = None
        commit_used = mem['commit_total_gb'] - mem['commit_avail_gb']
        if cpu_pct is not None:
            peak['cpu_pct'] = max(peak['cpu_pct'], cpu_pct)
        peak['commit_used_gb'] = max(peak['commit_used_gb'], commit_used)
        if (peak['ram_avail_gb_min'] is None
                or mem['ram_avail_gb'] < peak['ram_avail_gb_min']):
            peak['ram_avail_gb_min'] = mem['ram_avail_gb']
        if disk_free is not None and (peak['disk_free_gb_min'] is None
                                      or disk_free < peak['disk_free_gb_min']):
            peak['disk_free_gb_min'] = disk_free
        if cache_free is not None and (peak['cache_free_gb_min'] is None
                                       or cache_free < peak['cache_free_gb_min']):
            peak['cache_free_gb_min'] = cache_free
        if run is not None:
            self._emit(run, 'resources', elapsed_seconds=elapsed, cpu_percent=cpu_pct,
                       available_ram_gb=mem['ram_avail_gb'],
                       commit_used_gb=commit_used, disk_free_gb=disk_free,
                       cache_free_gb=cache_free, cache_dir=cache_dir)
        try:
            trace.write(
                '{iso},{el:.0f},{cpu},{avail:.2f},{total:.2f},{load:.0f},'
                '{cu:.2f},{ct:.2f},{df},{cf},"{prog}"\n'.format(
                    iso=time.strftime('%Y-%m-%dT%H:%M:%S'), el=elapsed,
                    cpu='' if cpu_pct is None else f'{cpu_pct:.1f}',
                    avail=mem['ram_avail_gb'], total=mem['ram_total_gb'],
                    load=mem['mem_load_pct'], cu=commit_used,
                    ct=mem['commit_total_gb'],
                    df='' if disk_free is None else f'{disk_free:.1f}',
                    cf='' if cache_free is None else f'{cache_free:.1f}',
                    prog=progress_line.replace('"', "'")[:120]))
            trace.flush()
        except (OSError, ValueError) as exc:
            self.logger.warning('Resource trace write failed: %s', exc)

    @staticmethod
    def _tail_line(path: str) -> str:
        if not os.path.isfile(path):
            return ''
        try:
            with open(path, 'rb') as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 4096))
                chunk = f.read().decode('utf-8', errors='replace')
            lines = [l.strip() for l in chunk.splitlines() if l.strip()]
            return lines[-1] if lines else ''
        except OSError:
            return ''
