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
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field

try:
    from module_base.settings_store import SettingsStore
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))
    from module_base.settings_store import SettingsStore

_THIS_DIR = os.path.dirname(os.path.realpath(__file__))
SCRIPTS_DIR = os.path.join(_THIS_DIR, 'RS_CLI', 'Scripts')
METADATA_DIR = os.path.join(_THIS_DIR, 'RS_CLI', 'Metadata')
ERRORS_DIR = os.path.join(_THIS_DIR, 'RS_CLI', 'Errors')

DEFAULT_INSTANCE_NAME = 'RS1'

# Console-subsystem children (tasklist, cmd) each pop a visible console
# window when their parent has none - over a long run that is hundreds of
# flashing windows stealing focus (owner report, 2026-07-23). Suppress on
# every helper subprocess; harmless for GUI-subsystem RealityScan.exe.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

# Newest install locations first; extend when Epic ships a new version.
EXECUTABLE_CANDIDATES = [
    r'C:\Program Files\Epic Games\RealityScan_2.2\RealityScan.exe',
    r'C:\Program Files\Capturing Reality\RealityScan 2.2\RealityScan.exe',
    r'C:\Program Files\Epic Games\RealityScan_2.1\RealityScan.exe',
    r'C:\Program Files\Capturing Reality\RealityScan 2.1\RealityScan.exe',
    r'C:\Program Files\Epic Games\RealityScan_2.0\RealityScan.exe',
]

# How long progress may stay silent before we log a stall warning. This is
# a warning only — large datasets can legitimately be quiet for a long time.
STALL_WARNING_SECONDS = 2 * 60 * 60
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


@dataclass
class WorkflowResult:
    success: bool
    return_code: int
    log_path: str = None
    errors: str = ''
    completed_processes: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0


class RealityScanCLI:
    """Shared launcher/monitor for every RealityScan CLI workflow."""

    def __init__(self, logger, settings: SettingsStore = None, instance_name: str = None):
        self.logger = logger
        self.settings = settings or SettingsStore()
        self.instance_name = (
            instance_name
            or self.settings.get('realityscan', 'instance_name')
            or DEFAULT_INSTANCE_NAME
        )

    # ------------------------------------------------------------------
    # Executable discovery
    # ------------------------------------------------------------------

    def find_executable(self) -> str:
        """Resolve RealityScan.exe: settings file, then RS_EXECUTABLE env
        var, then standard install locations (newest first)."""
        candidates = []

        configured = self.settings.get('realityscan', 'executable')
        if configured:
            candidates.append(configured)

        env_exe = os.environ.get('RS_EXECUTABLE')
        if env_exe:
            candidates.append(env_exe)

        candidates.extend(EXECUTABLE_CANDIDATES)

        for candidate in candidates:
            if candidate and os.path.isfile(candidate):
                return candidate

        raise FileNotFoundError(
            'RealityScan.exe not found. Set "realityscan.executable" in '
            'rs_settings.json or the RS_EXECUTABLE environment variable. '
            f'Tried: {candidates}'
        )

    # ------------------------------------------------------------------
    # Instance status (via RealityScan's own -getStatus)
    # ------------------------------------------------------------------

    def is_instance_running(self) -> bool:
        exe = self.find_executable()
        try:
            result = subprocess.run(
                [exe, '-getStatus', self.instance_name],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=STATUS_CALL_TIMEOUT_SECONDS,
                creationflags=_NO_WINDOW
            )
        except subprocess.TimeoutExpired:
            # A hung -getStatus means the instance exists but is unresponsive;
            # treat it as running so callers stay conservative.
            return True
        return result.returncode == 0

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
        """Ask a running instance to quit and wait for it to disappear."""
        if not self.is_instance_running():
            return True
        exe = self.find_executable()
        try:
            subprocess.run(
                [exe, '-delegateTo', self.instance_name, '-quit'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=STATUS_CALL_TIMEOUT_SECONDS,
                creationflags=_NO_WINDOW
            )
        except subprocess.TimeoutExpired:
            pass
        return self.wait_for_instance_shutdown()

    # ------------------------------------------------------------------
    # Locking (one orchestrator per instance name)
    # ------------------------------------------------------------------

    def _lock_path(self) -> str:
        return os.path.join(ERRORS_DIR, f'{self.instance_name}.lock')

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

    def _acquire_lock(self) -> None:
        os.makedirs(ERRORS_DIR, exist_ok=True)
        lock_path = self._lock_path()

        if os.path.isfile(lock_path):
            try:
                with open(lock_path, 'r', encoding='utf-8') as f:
                    holder_pid = int(f.read().strip() or 0)
            except (ValueError, OSError):
                holder_pid = 0

            if holder_pid and self._pid_alive(holder_pid):
                raise RuntimeError(
                    f'RealityScan instance "{self.instance_name}" is already '
                    f'being driven by PID {holder_pid} (lock: {lock_path}). '
                    'Use a different instance_name to run workflows in '
                    'parallel, or wait for the other run to finish.'
                )
            self.logger.warning('Removing stale RealityScan lock %s (PID %s is gone)', lock_path, holder_pid)
            os.remove(lock_path)

        # O_EXCL closes the window between the check above and creation.
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise RuntimeError(
                f'RealityScan instance "{self.instance_name}" was locked by '
                'another orchestrator while this one was starting up. '
                'Use a different instance_name to run workflows in parallel.'
            )
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(str(os.getpid()))

    def _release_lock(self) -> None:
        try:
            os.remove(self._lock_path())
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Marker files written by the instance / ErrorWriter hook
    # ------------------------------------------------------------------

    # Marker files are namespaced per instance so parallel instances (e.g.
    # one per GPU) can never read each other's state.

    def _marker(self, kind: str) -> str:
        names = {
            'progress': f'progress_{self.instance_name}.txt',
            'errors': f'errors_{self.instance_name}.txt',
            'results': f'results_{self.instance_name}.log',
        }
        return os.path.join(ERRORS_DIR, names[kind])

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

    def _read_marker(self, kind: str) -> str:
        path = self._marker(kind)
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

    def run_batch_script(self, script_name: str, args: list[str], log_dir: str,
                         display_output: bool = False, gpu_devices: str = None) -> WorkflowResult:
        """Run one RS_CLI workflow script and block until the RealityScan
        instance has finished and shut down.

        The batch script is responsible for per-command synchronisation
        (delegate → waitCompleted×2 → check errors.txt); this method is
        responsible for orchestration-level concerns: locking, marker
        hygiene, GPU pinning, live progress reporting, stall warnings, and
        verified instance shutdown.
        """
        exe = self.find_executable()
        script_path = os.path.join(SCRIPTS_DIR, script_name)
        if not os.path.isfile(script_path):
            raise FileNotFoundError(f'Workflow script not found: {script_path}')

        os.makedirs(log_dir, exist_ok=True)
        stamp = time.strftime('%Y-%m-%d_%H-%M-%S')
        log_path = os.path.join(log_dir, f'output_{stamp}.txt')
        # Shares the workflow log's timestamp so the trace and the narrative
        # of the same run are trivially paired. Every workflow gets one -
        # a crash is never predictable in advance.
        resource_csv = os.path.join(
            log_dir, f'resources_{os.path.splitext(script_name)[0]}_{stamp}.csv')

        env = os.environ.copy()
        env['RS_EXECUTABLE'] = exe
        env['RS_INSTANCE'] = self.instance_name
        gpu_devices = gpu_devices if gpu_devices is not None else self.settings.get('realityscan', 'gpu_devices')
        if gpu_devices:
            env['RS_GPU_DEVICES'] = str(gpu_devices)
            env['CUDA_VISIBLE_DEVICES'] = str(gpu_devices)

        self._acquire_lock()
        start_time = time.monotonic()
        try:
            # A leftover instance from a crashed run may be hours into an old
            # operation with our marker hooks still armed. Attaching to it
            # would queue behind that work and mix its results into ours, so
            # shut it down before starting anything.
            if self.is_instance_running():
                self.logger.warning(
                    'RealityScan instance "%s" is already running (probably left '
                    'over from an interrupted run); shutting it down before '
                    'starting the workflow.', self.instance_name)
                if not self.shutdown_instance():
                    raise RuntimeError(
                        f'RealityScan instance "{self.instance_name}" is still '
                        'running and did not respond to -quit. Close it manually '
                        '(check for a long-running operation first!) before '
                        'starting a new workflow.'
                    )

            self._clear_markers()

            creationflags = 0
            if os.name == 'nt':
                creationflags = (subprocess.CREATE_NEW_CONSOLE if display_output
                                 else subprocess.CREATE_NO_WINDOW)

            # display_output opens a visible console, so leave stdout attached
            # to it; otherwise capture everything in the log file.
            if display_output:
                # Invoke the .bat by absolute path WITHOUT an explicit
                # 'cmd /c' prefix: a bare script name fails to resolve when
                # NoDefaultCurrentDirectoryInExePath is set (e.g. Git Bash),
                # and prefixing cmd /c ourselves breaks when the checkout
                # path contains spaces (cmd strips the outer quotes).
                # Python's subprocess handles .bat quoting correctly.
                process = subprocess.Popen(
                    [script_path] + list(args),
                    cwd=SCRIPTS_DIR, env=env,
                    creationflags=creationflags,
                )
                self._monitor_until_exit(process, resource_csv)
                log_path = None
            else:
                with open(log_path, 'w', encoding='utf-8', errors='replace') as log_file:
                    process = subprocess.Popen(
                        [script_path] + list(args),
                        cwd=SCRIPTS_DIR, env=env,
                        stdout=log_file, stderr=subprocess.STDOUT,
                        creationflags=creationflags,
                    )
                    self._monitor_until_exit(process, resource_csv)

            return_code = process.returncode

            # The workflow ends by delegating -quit; make sure the instance is
            # really gone before anyone starts the next workflow.
            shutdown_ok = self.wait_for_instance_shutdown()

            # Read the markers only AFTER shutdown: the final operations can
            # still be running when the batch script exits, so an error from
            # them may arrive during the shutdown window.
            errors = self._read_marker('errors')
            results = [line for line in self._read_marker('results').splitlines() if line.strip()]

            if not shutdown_ok:
                self.logger.error(
                    'RealityScan instance "%s" did not shut down in time; '
                    'refusing to continue while it may still hold the scene.',
                    self.instance_name)
                return WorkflowResult(False, return_code, log_path, errors or 'instance did not shut down', results,
                                      time.monotonic() - start_time)

            success = return_code == 0 and not errors
            if not success:
                self.logger.error(
                    'RealityScan workflow %s failed (exit code %s). Errors: %s. Log: %s',
                    script_name, return_code, errors or '<none reported>', log_path)

            return WorkflowResult(success, return_code, log_path, errors, results,
                                  time.monotonic() - start_time)
        finally:
            self._release_lock()

    def _monitor_until_exit(self, process: subprocess.Popen,
                            resource_csv: str = None) -> None:
        """Poll the workflow process, relaying progress.txt updates and
        warning on stalls. No overall timeout by design.

        When `resource_csv` is given, a CPU/memory sample is appended every
        RESOURCE_SAMPLE_SECONDS and flushed immediately. Flushing per sample
        is the point: when RealityScan dies it takes its own log with it (the
        next instance overwrites Temp\\RealityScan.log), so the trace across
        the crash has to be durable as it is written, not at close.
        """
        progress_path = self._marker('progress')
        last_progress_line = ''
        last_errors = ''
        last_activity = time.monotonic()
        stall_warned = False
        low_memory_warned = False

        cpu = _CpuSampler()
        trace = None
        next_sample = 0.0
        started = time.monotonic()
        peak = {'cpu_pct': 0.0, 'commit_used_gb': 0.0, 'ram_avail_gb_min': None, 'disk_free_gb_min': None}
        if resource_csv:
            try:
                trace = open(resource_csv, 'w', encoding='utf-8', newline='')
                trace.write('iso_time,elapsed_s,cpu_pct,ram_avail_gb,'
                            'ram_total_gb,mem_load_pct,commit_used_gb,'
                            'commit_total_gb,disk_free_gb,progress\n')
                trace.flush()
            except OSError as exc:
                self.logger.warning('Could not open resource trace %s: %s',
                                    resource_csv, exc)
                trace = None

        try:
            self._monitor_loop(process, progress_path, last_progress_line,
                               last_errors, last_activity, stall_warned,
                               low_memory_warned, cpu, trace, next_sample,
                               started, peak)
        finally:
            if trace is not None:
                trace.close()
                self.logger.info(
                    'Resource peaks [%s]: CPU %.0f%%, commit used %.1f GB, '
                    'minimum available RAM %s, minimum free disk %s. Trace: %s',
                    self.instance_name, peak['cpu_pct'], peak['commit_used_gb'],
                    'n/a' if peak['ram_avail_gb_min'] is None
                    else f"{peak['ram_avail_gb_min']:.1f} GB",
                    'n/a' if peak['disk_free_gb_min'] is None
                    else f"{peak['disk_free_gb_min']:.1f} GB",
                    resource_csv)

    def _monitor_loop(self, process, progress_path, last_progress_line,
                      last_errors, last_activity, stall_warned,
                      low_memory_warned, cpu, trace, next_sample, started,
                      peak) -> None:
        while process.poll() is None:
            time.sleep(PROGRESS_POLL_SECONDS)

            if trace is not None:
                elapsed = time.monotonic() - started
                if elapsed >= next_sample:
                    next_sample = elapsed + RESOURCE_SAMPLE_SECONDS
                    self._sample_resources(trace, cpu, peak, elapsed,
                                           last_progress_line)

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
                self.logger.info('RealityScan [%s]: %s', self.instance_name, line)
                # '#timeout'-tagged progress is RealityScan reporting a
                # stalled operation: the elapsed counter keeps ticking, so
                # treating those lines as activity muted the stall warning
                # for 6 h while -importComponent hung (2026-07-23).
                if not line.rstrip().endswith('#timeout'):
                    last_activity = time.monotonic()
                    stall_warned = False

            errors = self._read_marker('errors')
            if errors and errors != last_errors:
                # The batch script aborts itself on the errors marker; we just
                # make the failure visible immediately instead of at the end.
                last_errors = errors
                self.logger.error('RealityScan [%s] reported an error: %s', self.instance_name, errors)

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
                        self.instance_name, STALL_WARNING_SECONDS / 3600, ram_note)
                else:
                    self.logger.warning(
                        'RealityScan [%s] has reported no progress for over %.1f hours. '
                        'Long silences are normal for very large datasets; check the '
                        'instance manually if this persists.%s',
                        self.instance_name, STALL_WARNING_SECONDS / 3600, ram_note)

    def _sample_resources(self, trace, cpu: '_CpuSampler', peak: dict,
                          elapsed: float, progress_line: str) -> None:
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
        try:
            trace.write(
                '{iso},{el:.0f},{cpu},{avail:.2f},{total:.2f},{load:.0f},'
                '{cu:.2f},{ct:.2f},{df},"{prog}"\n'.format(
                    iso=time.strftime('%Y-%m-%dT%H:%M:%S'), el=elapsed,
                    cpu='' if cpu_pct is None else f'{cpu_pct:.1f}',
                    avail=mem['ram_avail_gb'], total=mem['ram_total_gb'],
                    load=mem['mem_load_pct'], cu=commit_used,
                    ct=mem['commit_total_gb'],
                    df='' if disk_free is None else f'{disk_free:.1f}',
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
