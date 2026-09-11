"""Frontend control of the existing planned-command executor.

RealityScan commands remain exclusively inside RealityScanCLI. This module
communicates with that child through its per-attempt control/event contract.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import re
import subprocess
import threading
import time
from dataclasses import dataclass


_RETAINED_PROCESSES = {}
_RETAINED_LOCK = threading.Lock()
_EVENT_LINE_LIMIT = 64 * 1024
_TERMINAL_EVENTS = {"done", "failed", "cancelled"}


class OwnershipUnconfirmed(RuntimeError):
    """The frontend must retain its running state until explicit reconciliation."""

    def __init__(self, message, *, process=None, record=None, log_path=None):
        super().__init__(message)
        self.process, self.record, self.log_path = process, record, log_path
        if process is not None:
            # The controller catches this exception. Preserve the handle beyond
            # its exception scope; never infer release from a reused/dead PID.
            with _RETAINED_LOCK:
                _RETAINED_PROCESSES[id(process)] = (process, record, log_path)


@dataclass(frozen=True)
class RuntimeEventCursor:
    offset: int = 0
    identity: tuple | None = None


def _windows_process_snapshot(pid, *, owned_handle=None):
    """Read identity/liveness through Windows handles, never process-name tools.

    GetProcessTimes creation FILETIME distinguishes PID reuse. A signaled
    process handle proves exit; query errors do not. If OpenProcess fails, only
    a complete EnumProcesses snapshot excluding the PID can establish absence.
    """
    if os.name != "nt":
        raise OSError("Windows process identity inspection is unavailable on this platform")
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.GetProcessId.argtypes = [wintypes.HANDLE]
    kernel.GetProcessId.restype = wintypes.DWORD
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    handle = owned_handle if owned_handle is not None else kernel.OpenProcess(0x1000 | 0x100000, False, pid)
    if not handle:
        open_error = ctypes.get_last_error()
        kernel.K32EnumProcesses.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        kernel.K32EnumProcesses.restype = wintypes.BOOL
        for power in range(10, 21):
            ids = (wintypes.DWORD * (1 << power))()
            used = wintypes.DWORD()
            if not kernel.K32EnumProcesses(ids, ctypes.sizeof(ids), ctypes.byref(used)):
                raise ctypes.WinError(ctypes.get_last_error())
            if used.value < ctypes.sizeof(ids):
                if pid not in ids[:used.value // ctypes.sizeof(wintypes.DWORD)]:
                    return {"status": "absent", "evidence": "complete Windows process-ID snapshot"}
                raise ctypes.WinError(open_error)
        raise OSError("Could not obtain a complete Windows process-ID snapshot")
    try:
        if kernel.GetProcessId(handle) != pid:
            raise OSError("Process handle does not match the recorded PID")
        creation, exited, system, user = (wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exited),
                                      ctypes.byref(system), ctypes.byref(user)):
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        wait = kernel.WaitForSingleObject(handle, 0)
        if wait not in (0, 258):  # WAIT_OBJECT_0 / WAIT_TIMEOUT; not GetExitCode's ambiguous 259.
            raise ctypes.WinError(ctypes.get_last_error())
        return {"status": "running" if wait == 258 else "exited", "identity": {
            "schema": 1, "kind": "windows_process", "pid": pid,
            "created_filetime": (creation.dwHighDateTime << 32) | creation.dwLowDateTime,
            "image_path": buffer.value, "host": platform.node()}}
    finally:
        if owned_handle is None:
            kernel.CloseHandle(handle)


def capture_child_identity(process):
    """Capture from the exact Popen handle. Failure is recorded, not guessed.

    Normal execution still monitors that handle. A later restart cannot safely
    recover a record with missing identity based on a PID or user checkbox.
    """
    try:
        handle = getattr(process, "_handle", None)
        if handle is None:
            raise OSError("Exact Windows Popen handle is unavailable")
        return _windows_process_snapshot(process.pid, owned_handle=int(handle))["identity"]
    except Exception as exc:
        return {"schema": 1, "kind": "unconfirmed", "reason": str(exc)}


def inspect_owned_process(identity):
    """Read-only direct-child identity verdict; never signal/kill/open by name."""
    report = {"status": "unconfirmed", "confirmed_not_running": False}
    try:
        if (not isinstance(identity, dict) or identity.get("schema") != 1
                or identity.get("kind") != "windows_process"
                or type(identity.get("pid")) is not int or not 0 < identity["pid"] < 2 ** 32
                or type(identity.get("created_filetime")) is not int or identity["created_filetime"] <= 0
                or not isinstance(identity.get("image_path"), str) or not Path(identity["image_path"]).is_absolute()
                or not identity.get("host") or identity["host"] != platform.node()):
            raise ValueError("Missing/invalid process creation identity or different host")
        observed = _windows_process_snapshot(identity["pid"])
        if observed["status"] == "absent":
            return report | {"status": "absent", "confirmed_not_running": True, "evidence": observed["evidence"]}
        current = observed["identity"]
        if current["created_filetime"] != identity["created_filetime"]:
            return report | {"status": "pid_reused", "confirmed_not_running": True, "observed_identity": current}
        if os.path.normcase(os.path.normpath(current["image_path"])) != os.path.normcase(os.path.normpath(identity["image_path"])):
            raise ValueError("Same PID/creation time has conflicting executable identity")
        if observed["status"] not in {"running", "exited"}:
            raise ValueError("Unknown process query result")
        return report | {"status": "same_process_" + observed["status"],
                         "confirmed_not_running": observed["status"] == "exited", "observed_identity": current}
    except Exception as exc:
        return report | {"reason": str(exc)}


def inspect_recovery(record, state, *, expected_project_id, expected_attempt_id):
    """Read-only recovery proof. The controller owns any subsequent state change.

    Requires trusted plan/state binding, exact direct-child absence/exit, and for
    RS stages fresh terminal runtime release. CLI status None is NOT an absence
    proof, so missing release evidence remains unconfirmed. No journals erased.
    """
    result = {"can_recover": False, "status": "unconfirmed", "automatic_changes": False}
    try:
        for key, expected in (("project_id", expected_project_id), ("project_attempt_id", expected_attempt_id)):
            if not isinstance(expected, str) or not expected or record.get(key) != expected or state.get(key) != expected:
                raise ValueError(f"Untrusted/mismatched recovery binding: {key}")
        if record.get("stage") != state.get("stage") or not state.get("stage"):
            raise ValueError("Recovery stage does not match its persisted plan")
        if state.get("needs_realityscan") is not bool(record.get("needs_realityscan")):
            raise ValueError("Recovery application ownership scope changed")
        if (state.get("launch_attempted") is not True or not isinstance(state.get("child_identity"), dict)
                or state.get("pid") != state["child_identity"].get("pid")):
            raise ValueError("Incomplete or conflicting persisted child identity")
        child = inspect_owned_process(state.get("child_identity"))
        result["child"] = child
        if not child["confirmed_not_running"]:
            return result | {"status": "active" if child["status"] == "same_process_running" else "unconfirmed"}
        if record.get("needs_realityscan"):
            channel_keys = ("RS_RUN_ID", "RS_RUNTIME_ROOT", "RS_ERRORS_DIR", "RS_CONTROL_FILE", "RS_EVENT_FILE", "RS_INSTANCE", "RS_EXECUTABLE")
            selected = {key: record.get("env", {}).get(key) for key in channel_keys}
            if state.get("runtime") != selected:
                raise ValueError("Recovery runtime channel does not match the persisted execution")
            saved = state["runtime_event_cursor"]
            if type(saved["offset"]) is not int or saved["offset"] < 0:
                raise ValueError("Invalid persisted runtime event boundary")
            identity = saved.get("identity")
            if identity is not None and (not isinstance(identity, (list, tuple)) or len(identity) != 2
                                         or any(type(item) is not int for item in identity)):
                raise ValueError("Invalid persisted event-file identity")
            require_runtime_release(record, cursor=RuntimeEventCursor(saved["offset"], tuple(identity) if identity is not None else None))
            result["runtime"] = {"status": "terminal_release_verified"}
        return result | {"can_recover": True, "status": "quiescent"}
    except Exception as exc:
        return result | {"reason": str(exc)}


def _channel(record):
    env = record.get("env", {})
    if not isinstance(env, dict):
        raise ValueError("Runtime environment must be an object")
    parent = env.get("RS_RUN_ID")
    if not isinstance(parent, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", parent):
        raise ValueError("Runtime parent run ID is missing or invalid")
    root, path = env.get("RS_RUNTIME_ROOT"), env.get("RS_EVENT_FILE")
    if not root or not path or not Path(root).is_absolute() or not Path(path).is_absolute():
        raise ValueError("Runtime channel requires absolute root/event paths")
    root, path = Path(root).resolve(), Path(path).resolve()
    if path.parent != root:
        raise ValueError("Runtime event file must be directly inside its attempt root")
    return env, parent, root, path


def runtime_event_cursor(record):
    """Read-only prelaunch boundary: older stages cannot certify this exit."""
    if not record.get("needs_realityscan"):
        return RuntimeEventCursor()
    path = (record.get("env") or {}).get("RS_EVENT_FILE")
    if not path:
        return RuntimeEventCursor()
    try:
        with Path(path).open("rb") as stream:
            st = os.fstat(stream.fileno())
            if st.st_size:
                stream.seek(-1, os.SEEK_END)
                if stream.read(1) != b"\n":
                    raise OwnershipUnconfirmed("Earlier runtime evidence has an incomplete final event; reconcile before another launch")
            return RuntimeEventCursor(st.st_size, (st.st_dev, st.st_ino))
    except FileNotFoundError:
        return RuntimeEventCursor()
    except (OSError, ValueError, TypeError) as exc:
        raise OwnershipUnconfirmed("Cannot establish the runtime event boundary before launch") from exc


def _event(line):
    if len(line) > _EVENT_LINE_LIMIT or not line.endswith(b"\n"):
        raise ValueError("Runtime event is oversized or incomplete")
    event = json.loads(line)
    if not isinstance(event, dict) or not isinstance(event.get("data"), dict):
        raise ValueError("Runtime event and its data must be objects")
    for field in ("parent_run_id", "run_id"):
        if not isinstance(event.get(field), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", event[field]):
            raise ValueError(f"Invalid runtime {field}")
    if type(event.get("sequence")) is not int or event["sequence"] < 1:
        raise ValueError("Invalid runtime event sequence")
    if not isinstance(event.get("kind"), str) or not event["kind"]:
        raise ValueError("Invalid runtime event kind")
    if "ownership_retained" in event["data"] and type(event["data"]["ownership_retained"]) is not bool:
        raise ValueError("Runtime ownership flag must be a boolean")
    return event


def require_runtime_release(record, *, cursor=None):
    if not record.get("needs_realityscan"):
        return
    try:
        _, parent, _, path = _channel(record)
        cursor = cursor or RuntimeEventCursor()
        states = {}
        with path.open("rb") as stream:
            st = os.fstat(stream.fileno())
            if st.st_size < cursor.offset or (cursor.identity is not None and cursor.identity != (st.st_dev, st.st_ino)):
                raise ValueError("Runtime event channel was replaced or truncated")
            stream.seek(cursor.offset)
            while line := stream.readline(_EVENT_LINE_LIMIT + 1):
                event = _event(line)
                if event["parent_run_id"] != parent:
                    continue
                run_id = event["run_id"]
                previous, _ = states.get(run_id, (0, False))
                if event["sequence"] != previous + 1 or (previous == 0 and event["kind"] != "prepared"):
                    raise ValueError("Runtime events are missing, duplicated or out of order")
                released = event["kind"] in _TERMINAL_EVENTS and event["data"].get("ownership_retained") is False
                states[run_id] = (event["sequence"], released)
            after = os.fstat(stream.fileno())
            if (st.st_size, st.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError("Runtime event channel changed during release inspection")
        if not states or not all(released for _, released in states.values()):
            raise ValueError("Every current child requires a terminal ownership release event")
    except Exception as exc:
        raise OwnershipUnconfirmed("Runtime ownership evidence is unavailable; reconcile before restarting") from exc


class ExecutionControl:
    def __init__(self):
        self._requested = threading.Event()
        self._lock = threading.Lock()
        self._mode = "after_step"

    @property
    def cancellation_requested(self):
        return self._requested.is_set()

    @property
    def mode(self):
        with self._lock:
            return self._mode

    def snapshot(self):
        with self._lock:
            return self._requested.is_set(), self._mode

    def request_cancel(self, mode="after_step"):
        if mode not in ("after_step", "abort_current"):
            raise ValueError("Unknown cancellation mode")
        # An immediate abort may strengthen a prior stop-after-step request.
        with self._lock:
            if mode == "abort_current" or not self._requested.is_set():
                self._mode = mode
            self._requested.set()


def wait_planned_process(process, record, log_path, control, observer=None, *, cursor=None):
    """Wait for the exact child, or report retained/ambiguous ownership.

    Unrecoverable wait errors escape as OwnershipUnconfirmed, never as a generic
    failure the controller could interpret as release. Presentation errors are
    isolated from process ownership. Failed abort delivery is retried while the
    same child is monitored; a request is not a confirmed termination.
    """
    from rs import _write_json

    control = control or ExecutionControl()
    sent = None
    log_cursor = 0
    event_cursor = cursor.offset if cursor else 0
    env = record.get("env", {})

    def emit(event):
        if observer:
            try:
                observer(event)
            except KeyboardInterrupt:
                control.request_cancel("abort_current")
            except Exception:
                # Presentation must never abandon ownership of a running child.
                pass

    def stream_output():
        nonlocal log_cursor, event_cursor
        if not observer:
            return 0
        try:
            with Path(log_path).open("r", encoding="utf-8", errors="replace") as log:
                log.seek(log_cursor)
                chunk = log.read(32768)
                log_cursor = log.tell()
        except (OSError, ValueError):
            chunk = ""
        if chunk:
            emit({"kind": "log", "message": chunk.rstrip(), "path": str(log_path)})
        count = 0
        if env.get("RS_EVENT_FILE"):
            try:
                # Read bytes: an in-flight partial UTF-8 codepoint must not
                # crash monitoring or advance past the incomplete JSONL record.
                with Path(env["RS_EVENT_FILE"]).open("rb") as stream:
                    stream.seek(event_cursor)
                    for _ in range(100):
                        position = stream.tell()
                        line = stream.readline(_EVENT_LINE_LIMIT + 1)
                        if not line.endswith(b"\n"):
                            stream.seek(position)
                            break
                        count += 1
                        try:
                            event = _event(line)
                        except (ValueError, TypeError):
                            emit({"kind": "error", "message": "Malformed runtime event; run still monitored"})
                        else:
                            if event["parent_run_id"] == env.get("RS_RUN_ID"):
                                emit({"kind": "runtime", "event": event})
                    event_cursor = stream.tell()
            except (OSError, ValueError, TypeError):
                pass  # Strict release inspection separately judges evidence.
        return count

    try:
        while True:
            try:
                requested, mode = (control.snapshot() if isinstance(control, ExecutionControl)
                                   else (control.cancellation_requested, control.mode))
                if requested and sent != mode:
                    delivered = False
                    try:
                        if record.get("needs_realityscan"):
                            _, parent, root, event_path = _channel(record)
                            raw = env.get("RS_CONTROL_FILE")
                            if not raw or not Path(raw).is_absolute():
                                raise ValueError("Missing absolute runtime control path")
                            path = Path(raw).resolve()
                            if (path.parent != root or path == event_path or root.name != parent
                                    or root.parent.name.lower() != "tmp" or root.parent.parent.name.lower() != "proc"):
                                raise ValueError("Refused unsafe runtime control path")
                            _write_json(path, {"run_id": parent, "mode": mode, "requested_at": time.time()})
                        elif mode == "abort_current":
                            # Exact owned non-RS child only. Do not poll before
                            # waiting: a poll error is not evidence of its exit.
                            process.terminate()
                        delivered = True
                    except (OSError, ValueError, TypeError) as exc:
                        emit({"kind": "error", "message": f"Cancellation delivery failed: {exc}; ownership retained"})
                    if delivered:
                        sent = mode
                    emit({"kind": "state", "state": "cancel_requested", "ownership_released": False,
                          "message": f"Requested {mode}; waiting for confirmed shutdown"})
                stream_output()
                try:
                    code = process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    continue
                if type(code) is not int:
                    raise RuntimeError("Child wait returned no confirmed integer exit code")
                # Include events appended just before exit, including a backlog
                # larger than one presentation batch. No process-name inference.
                while stream_output():
                    pass
                return code
            except KeyboardInterrupt:
                control.request_cancel("abort_current")
    except BaseException as exc:
        raise OwnershipUnconfirmed("Cannot monitor the owned child safely; ownership must be reconciled",
                                   process=process, record=record, log_path=log_path) from exc
