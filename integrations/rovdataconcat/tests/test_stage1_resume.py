"""
Tests for the stage-1 (main.py) resume and failure-propagation fix.

Two coupled defects, one root cause -- nothing durably recorded whether a
step actually completed:

1. Resume was step-granular while the outputs are dive-granular. The gate
   globbed for any ONE output file, so a run that died partway through the
   dive loop left the first dive's CSV behind and the next run skipped the
   whole step, silently shipping an expedition missing every dive after the
   failure.
2. Every processor guards its inputs with bare "return"s that fire before
   its RunReport exists. Those exit process_data() without raising, and
   run_step() reported them as 'ok', so the pipeline continued on absent
   data and main() exited 0.

Both are now decided by the JSON provenance sidecar, which finalize() is the
only thing that writes.

Run from the repository root:  python -m pytest tests/ -v
"""

import json
import sys
import types
from pathlib import Path

import pytest

import main
from main import run_step, step_completed, RESUMABLE_STEPS
from processors.report import (
    RunReport,
    stage_status,
    stage_completed_ok,
    stage_report_path,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_sidecar(root, stage, status=None, events=None):
    """Write a sidecar by hand, so pre-'status' payloads can be simulated."""
    reports = Path(root) / "RUMI_processed" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    payload = {"stage": stage, "events": events or []}
    if status is not None:
        payload["status"] = status
    (reports / f"{stage}.json").write_text(json.dumps(payload), encoding="utf-8")


def fake_module(name, fn):
    """A stand-in for processors.<name> with a process_data of our choosing."""
    mod = types.ModuleType(f"processors.{name}")
    mod.process_data = fn
    return mod


def finalizing(stage, root, error=False):
    """A process_data that behaves like a real processor and finalizes."""
    def _run(root_dir):
        report = RunReport(stage, Path(root_dir) / "RUMI_processed")
        if error:
            report.error("no-data", "nothing parsed")
        report.finalize()
    return _run


# ---------------------------------------------------------------------------
# The sidecar as a completion record
# ---------------------------------------------------------------------------

class TestStageStatus:
    def test_missing_sidecar_is_none_not_ok(self, tmp_path):
        # None is the load-bearing case: it means "never reached finalize()".
        assert stage_status(tmp_path / "RUMI_processed", "process_dat") is None
        assert stage_completed_ok(tmp_path / "RUMI_processed", "process_dat") is False

    def test_clean_sidecar_is_ok(self, tmp_path):
        write_sidecar(tmp_path, "process_dat", status="ok")
        assert stage_status(tmp_path / "RUMI_processed", "process_dat") == "ok"

    def test_error_status_is_error(self, tmp_path):
        write_sidecar(tmp_path, "process_dat", status="error")
        assert stage_completed_ok(tmp_path / "RUMI_processed", "process_dat") is False

    def test_unreadable_sidecar_is_none(self, tmp_path):
        reports = tmp_path / "RUMI_processed" / "reports"
        reports.mkdir(parents=True)
        (reports / "process_dat.json").write_text("{ not json", encoding="utf-8")
        assert stage_status(tmp_path / "RUMI_processed", "process_dat") is None

    def test_warnings_do_not_fail_a_stage(self, tmp_path):
        write_sidecar(tmp_path, "usbl_sdyn", events=[
            {"severity": "warning", "category": "no-data", "message": "one dive empty"},
            {"severity": "anomaly", "category": "time-gaps", "message": "gap"},
        ])
        assert stage_status(tmp_path / "RUMI_processed", "usbl_sdyn") == "ok"

    def test_pre_status_sidecar_classified_from_events(self, tmp_path):
        # Payloads written before 'status' existed must still resume correctly.
        write_sidecar(tmp_path, "usbl_sdyn", events=[
            {"severity": "error", "category": "no-data", "message": "none parsed"},
        ])
        assert stage_status(tmp_path / "RUMI_processed", "usbl_sdyn") == "error"

    def test_finalize_records_status(self, tmp_path):
        processed = tmp_path / "RUMI_processed"
        RunReport("process_dat", processed).finalize()
        payload = json.loads(
            stage_report_path(processed, "process_dat").read_text(encoding="utf-8")
        )
        assert payload["status"] == "ok"

        report = RunReport("usbl_sdyn", processed)
        report.error("no-data", "none parsed")
        report.finalize()
        payload = json.loads(
            stage_report_path(processed, "usbl_sdyn").read_text(encoding="utf-8")
        )
        assert payload["status"] == "error"


# ---------------------------------------------------------------------------
# THE REGRESSION: partial dive coverage must not read as a completed step
# ---------------------------------------------------------------------------

class TestPartialDiveCoverage:
    def test_one_dives_output_does_not_complete_the_step(self, tmp_path):
        # Exactly the H2049-succeeded-then-crashed shape. The old gate globbed
        # '*/[!.]*_pitch_roll_heading_octans.csv' and returned True here.
        dive = tmp_path / "RUMI_processed" / "H2049"
        dive.mkdir(parents=True)
        (dive / "NA165_H2049_pitch_roll_heading_octans.csv").write_text(
            "x", encoding="utf-8"
        )
        assert step_completed("process_dat", tmp_path) is False

    def test_completed_step_is_skipped(self, tmp_path):
        write_sidecar(tmp_path, "process_dat", status="ok")
        assert step_completed("process_dat", tmp_path) is True

    def test_stillcam_is_never_resume_skipped(self, tmp_path):
        # It resumes per image internally and must run to pick up new captures.
        assert "stillcam_images" not in RESUMABLE_STEPS
        write_sidecar(tmp_path, "stillcam_images", status="ok")
        assert step_completed("stillcam_images", tmp_path) is False


# ---------------------------------------------------------------------------
# Failure propagation: returning normally is not success
# ---------------------------------------------------------------------------

class TestRunStepFailurePropagation:
    def test_silent_early_return_is_failed(self, tmp_path):
        # The bare "return" on a missing-input path: no exception, no sidecar.
        mod = fake_module("process_dat", lambda root_dir: None)
        assert run_step(mod, tmp_path) == "failed"

    def test_finalized_error_is_failed(self, tmp_path):
        mod = fake_module("usbl_sdyn", finalizing("usbl_sdyn", tmp_path, error=True))
        assert run_step(mod, tmp_path) == "failed"

    def test_raising_step_is_failed(self, tmp_path):
        def boom(root_dir):
            raise RuntimeError("stage exploded")
        assert run_step(fake_module("process_dat", boom), tmp_path) == "failed"

    def test_clean_finalize_is_ok(self, tmp_path):
        mod = fake_module("process_dat", finalizing("process_dat", tmp_path))
        assert run_step(mod, tmp_path) == "ok"

    def test_completed_step_skips_and_force_reruns(self, tmp_path):
        calls = []

        def record(root_dir):
            calls.append(1)
            finalizing("process_dat", tmp_path)(root_dir)

        mod = fake_module("process_dat", record)
        assert run_step(mod, tmp_path) == "ok"
        assert run_step(mod, tmp_path) == "skipped"
        assert run_step(mod, tmp_path, force=True) == "ok"
        assert len(calls) == 2

    def test_crashed_step_reruns_rather_than_resuming(self, tmp_path):
        # Crash on the first pass, succeed on the second -- the crash must not
        # leave anything behind that lets the rerun skip.
        state = {"first": True}

        def flaky(root_dir):
            if state["first"]:
                state["first"] = False
                dive = Path(root_dir) / "RUMI_processed" / "H2049"
                dive.mkdir(parents=True, exist_ok=True)
                (dive / "NA165_H2049_pitch_roll_heading_octans.csv").write_text(
                    "x", encoding="utf-8"
                )
                raise RuntimeError("died at dive 15 of 19")
            finalizing("process_dat", tmp_path)(root_dir)

        mod = fake_module("process_dat", flaky)
        assert run_step(mod, tmp_path) == "failed"
        assert run_step(mod, tmp_path) == "ok"


# ---------------------------------------------------------------------------
# End to end: a silently-failing step must not exit 0
# ---------------------------------------------------------------------------

class TestMainExitCode:
    def test_main_exits_nonzero_when_a_step_returns_silently(self, monkeypatch, tmp_path):
        (tmp_path / "raw").mkdir()
        monkeypatch.setattr(
            main.dive_summaries, "process_data", lambda root_dir: None, raising=False
        )
        monkeypatch.setattr(sys, "argv", ["main.py", "--dir", str(tmp_path)])
        assert main.main() == 1
