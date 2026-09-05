"""Subprocess runner: stream a LaunchPlan's output as Textual messages.

One worker thread per run; every stdout/stderr line becomes a LogLine
message, RealityScan `#progress` heartbeats become ProgressUpdate, and the
exit code arrives as RunFinished. The UI stays responsive and the child is
never polled.
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
from pathlib import Path

from textual.message import Message

REPO = Path(__file__).resolve().parent.parent

# "20533 0.67 33.41 17.11 #progress"  ->  op, fraction, elapsed, eta
_PROGRESS = re.compile(
    r"(\d+)\s+([01]\.\d+)\s+([\d.]+)\s+([\d.]+)\s+#(progress|started|completed)")


class LogLine(Message):
    def __init__(self, line: str) -> None:
        self.line = line
        super().__init__()


class ProgressUpdate(Message):
    def __init__(self, fraction: float, eta_s: float, op: str) -> None:
        self.fraction = fraction
        self.eta_s = eta_s
        self.op = op
        super().__init__()


class RunFinished(Message):
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode
        super().__init__()


class CommandRunner:
    """Owns exactly one child process; post_target receives the messages."""

    def __init__(self, post_target) -> None:
        self._post = post_target.post_message
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, plan) -> None:
        """`plan` is anything with argv + env (session.StageCommand)."""
        if self.running:
            raise RuntimeError("a stage is already running")
        env = dict(os.environ)
        env.update(plan.env)
        cwd = getattr(plan, "cwd", str(REPO))
        # stdin=DEVNULL: a child that reaches input() must get EOF (and take
        # its stored-default path) - never block invisibly on an inherited
        # console (the exact hang the final review found in the drivers).
        self._proc = subprocess.Popen(
            plan.argv, cwd=cwd, env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1)
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def terminate(self) -> None:
        """Stop the child. RealityScan instances shut down via their own
        workflow paths; this only kills the DRIVER process - which is why
        stage drivers are written to be resumable."""
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    def _pump(self) -> None:
        assert self._proc and self._proc.stdout
        for raw in self._proc.stdout:
            line = raw.rstrip("\r\n")
            if not line:
                continue
            m = _PROGRESS.search(line)
            if m and m.group(5) == "progress":
                self._post(ProgressUpdate(float(m.group(2)),
                                          float(m.group(4)), m.group(1)))
            self._post(LogLine(line))
        self._proc.wait()
        self._post(RunFinished(self._proc.returncode))
