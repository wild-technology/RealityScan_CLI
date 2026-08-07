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
import tempfile
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

        Returns None when the instance does not exist (non-zero errorlevel),
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
                except subprocess.TimeoutExpired:
                    return {'raw': '', 'timeout': True}
            if result.returncode != 0:
                return None
            with open(tmp_path, 'r', encoding='utf-8', errors='replace') as f:
                raw = f.read().strip()
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return self._parse_status_line(raw)

    # ------------------------------------------------------------------
    # Locking (one orchestrator per instance name)
    # ------------------------------------------------------------------

    def _lock_path(self, instance: str = None) -> str:
        # '*' (attach mode's "first available instance") is not a legal
        # filename character; all wildcard attaches share one lock, which is
        # the right scope anyway - '*' is ambiguous by nature, so two
        # concurrent wildcard drivers could race for the same instance.
        inst = (instance or self.instance_name).replace('*', 'WILDCARD')
        return os.path.join(ERRORS_DIR, f'{inst}.lock')

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

    def _acquire_lock(self, instance: str = None) -> None:
        inst = instance or self.instance_name
        os.makedirs(ERRORS_DIR, exist_ok=True)
        lock_path = self._lock_path(inst)

        if os.path.isfile(lock_path):
            try:
                with open(lock_path, 'r', encoding='utf-8') as f:
                    holder_pid = int(f.read().strip() or 0)
            except (ValueError, OSError):
                holder_pid = 0

            if holder_pid and self._pid_alive(holder_pid):
                raise RuntimeError(
                    f'RealityScan instance "{inst}" is already '
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
                f'RealityScan instance "{inst}" was locked by '
                'another orchestrator while this one was starting up. '
                'Use a different instance_name to run workflows in parallel.'
            )
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(str(os.getpid()))

    def _release_lock(self, instance: str = None) -> None:
        try:
            os.remove(self._lock_path(instance))
        except OSError:
            pass

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
        # a crash is never predictable in advance. basename() because
        # script_name may be an absolute path (tests use stub scripts).
        resource_csv = os.path.join(
            log_dir,
            f'resources_{os.path.splitext(os.path.basename(script_name))[0]}_{stamp}.csv')

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

    def run_attach_script(self, script_name: str, args: list[str],
                          log_dir: str, instance: str = '*') -> WorkflowResult:
        """Run one RS_CLI workflow script against an ALREADY-RUNNING
        RealityScan instance (attach mode - e.g. ModelToFinal.bat).

        The attach-mode counterpart to :meth:`run_batch_script` for
        workflows that finish a scene another session created (a GUI
        reconstruction, an Epic-Launcher instance). ``instance`` may be a
        concrete name or ``*`` ("first available instance" - only safe with
        a single instance running). The differences from
        ``run_batch_script`` are each deliberate and commented inline.
        """
        exe = self.find_executable()
        script_path = os.path.join(SCRIPTS_DIR, script_name)
        if not os.path.isfile(script_path):
            raise FileNotFoundError(f'Workflow script not found: {script_path}')

        # Difference (a): REFUSE to start an instance. run_batch_script's
        # contract is "own the instance's whole lifecycle"; attach mode's
        # is "never boot, never reset". Booting from here would go through
        # startRealityScan.bat, whose already-running branch issues
        # '-newScene -deleteAutosave' and destroys the very scene this
        # workflow exists to finish (the ON2026 near-miss, HANDOFF
        # 2026-08-07).
        status = self.get_instance_status(instance)
        if status is None:
            raise RuntimeError(
                f'No reachable RealityScan instance "{instance}" '
                '(-getStatus failed). Attach mode never boots an instance: '
                'start RealityScan and load the project first (GUI, Epic '
                'Launcher, or startRealityScan.bat), then re-run - or pass '
                'the right instance name.')
        if status.get('timeout'):
            # Exists but unresponsive - possibly hours into a legitimate
            # operation, possibly hung (a relocated .rsalign import pins an
            # instance in a #timeout state forever). Attaching is still the
            # conservative move - refusing could strand a busy instance's
            # finished scene - but the operator must know which it is.
            self.logger.warning(
                'RealityScan instance "%s" exists but -getStatus timed out '
                'after %s s - it may be mid-operation or hung. The workflow '
                'will block on -waitCompleted until it responds; check the '
                'GUI if this stalls.', instance, STATUS_CALL_TIMEOUT_SECONDS)

        os.makedirs(log_dir, exist_ok=True)
        stamp = time.strftime('%Y-%m-%d_%H-%M-%S')
        log_path = os.path.join(log_dir, f'output_{stamp}.txt')
        # Difference (e) is a NON-difference: attach runs still get the
        # same run log and resource CSV as batch runs, same naming scheme.
        resource_csv = os.path.join(
            log_dir,
            f'resources_{os.path.splitext(os.path.basename(script_name))[0]}_{stamp}.csv')

        env = os.environ.copy()
        env['RS_EXECUTABLE'] = exe
        # No RS_GPU_DEVICES/CUDA_VISIBLE_DEVICES here: GPU pinning is a
        # boot-time property of the instance, and attach mode never boots.

        self._acquire_lock(instance)
        start_time = time.monotonic()
        try:
            # Difference (b): NO shutdown-before-start, NO shutdown-after,
            # and no FOREIGN marker clearing. The instance and its scene
            # belong to whoever booted it. errors_<instance>.txt exists
            # ONLY for instances booted by startRealityScan.bat - its
            # absence is not success, and clearing a foreign instance's
            # markers would corrupt the owner's error detection mid-run.
            #
            # OWN-instance exception (live gate B9, 2026-08-07): when
            # attaching to the instance THIS checkout owns, a previous
            # run's ErrorWriter entries are ours and legitimately stale -
            # they tripped ModelToFinal's own-marker gate on the very
            # first delegated op. Clear errors/results exactly as
            # run_batch_script would. NEVER progress_<instance>.txt: the
            # live instance holds it open via -writeProgress (deleting it
            # raises WinError 32; truncation is pointless - the writer
            # keeps appending).
            if instance == self.instance_name:
                for kind in ('errors', 'results'):
                    path = self._marker(kind)
                    if os.path.isfile(path):
                        try:
                            os.remove(path)
                        except OSError:
                            try:
                                # a reader may hold it transiently; truncate
                                with open(path, 'w', encoding='utf-8'):
                                    pass
                            except OSError:
                                # Second sharing violation: warn and let the
                                # .bat's own marker gate produce the loud
                                # abort - do not kill the attach before the
                                # workflow even starts (clean-sweep 2026-08-07).
                                self.logger.warning(
                                    'Could not clear stale own marker %s - '
                                    'the workflow marker gate may abort on it.',
                                    path)

            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

            # Difference (c): the target instance rides as the script's
            # FIRST argument (ModelToFinal.bat: %1 -> RS_TARGET), not via
            # RS_INSTANCE. RS_INSTANCE keeps meaning "the instance this
            # checkout boots and owns", which is what lets the script's own
            # marker-file gate tell own markers from foreign ones.
            with open(log_path, 'w', encoding='utf-8', errors='replace') as log_file:
                process = subprocess.Popen(
                    [script_path, instance] + list(args),
                    cwd=SCRIPTS_DIR, env=env,
                    stdout=log_file, stderr=subprocess.STDOUT,
                    creationflags=creationflags,
                )
                # Difference (d): same progress-tailing/stall/resource
                # machinery as batch mode, pointed at the TARGET instance's
                # marker files - which may simply not exist (wildcard or
                # foreign instance). The monitor already degrades every
                # missing marker read to '', so it tolerates that.
                self._monitor_until_exit(process, resource_csv,
                                         marker_instance=instance)

            return_code = process.returncode

            # Success is the script's exit code: its :run gate baselines
            # rev/lastError from -getStatus around every delegated command
            # (see ModelToFinal.bat), because marker files cannot be
            # trusted in attach mode. Never gate on marker absence here.
            errors = ''
            if return_code != 0:
                final = self.get_instance_status(instance) or {}
                last_error = final.get('lastError')
                if last_error not in (None, 0):
                    errors = f'lastError:{last_error}'
                else:
                    errors = f'workflow exited with code {return_code}'
                self.logger.error(
                    'RealityScan attach workflow %s on "%s" failed '
                    '(exit code %s, %s). Log: %s',
                    script_name, instance, return_code, errors, log_path)

            # Informational only: results_<instance>.log is never cleared
            # by attach mode, so for a CLI-booted own instance it may also
            # contain lines from earlier operations.
            results = [line for line in
                       self._read_marker('results', instance).splitlines()
                       if line.strip()]

            return WorkflowResult(return_code == 0, return_code, log_path,
                                  errors, results,
                                  time.monotonic() - start_time)
        finally:
            self._release_lock(instance)

    def _monitor_until_exit(self, process: subprocess.Popen,
                            resource_csv: str = None,
                            marker_instance: str = None) -> None:
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
        low_memory_warned = False

        cpu = _CpuSampler()
        trace = None
        next_sample = 0.0
        started = time.monotonic()
        peak = {'cpu_pct': 0.0, 'commit_used_gb': 0.0, 'ram_avail_gb_min': None, 'disk_free_gb_min': None,
                'cache_free_gb_min': None}
        if resource_csv:
            try:
                trace = open(resource_csv, 'w', encoding='utf-8', newline='')
                trace.write('iso_time,elapsed_s,cpu_pct,ram_avail_gb,'
                            'ram_total_gb,mem_load_pct,commit_used_gb,'
                            'commit_total_gb,disk_free_gb,cache_free_gb,progress\n')
                trace.flush()
            except OSError as exc:
                self.logger.warning('Could not open resource trace %s: %s',
                                    resource_csv, exc)
                trace = None

        try:
            self._monitor_loop(process, progress_path, last_progress_line,
                               last_errors, last_activity, stall_warned,
                               low_memory_warned, cpu, trace, next_sample,
                               started, peak, marker_instance)
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
                      peak, marker_instance=None) -> None:
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

            errors = self._read_marker('errors', marker_instance)
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
        # ...and on the CACHE drive, which is a DIFFERENT disk and is the one
        # that actually killed the hull model three times. The column above
        # watched the project drive and read 773.9 GB free for a whole run
        # while this one hit zero (2026-07-26).
        cache_dir = os.environ.get('RS_CACHE_DIR')
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
