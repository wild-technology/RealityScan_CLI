"""A progress reader must not make an atomic metadata update fail instantly."""
import os

import pytest

from module_base.atomic_io import replace_file


@pytest.mark.skipif(os.name != "nt", reason="Windows sharing violations")
def test_transient_reader_lock_retries_without_deleting_old_record(tmp_path, monkeypatch):
    target, pending = tmp_path / "progress.json", tmp_path / "pending"
    target.write_text("old")
    pending.write_text("new")
    original = os.replace
    calls = []
    def locked_once(source, destination):
        calls.append(1)
        if len(calls) == 1:
            error = PermissionError("Reader denies replacement")
            error.winerror = 5
            raise error
        assert target.read_text() == "old"
        original(source, destination)
    monkeypatch.setattr(os, "replace", locked_once)
    replace_file(pending, target)
    assert target.read_text() == "new" and len(calls) == 2


def test_nonsharing_failure_preserves_previous_record_without_retry(tmp_path, monkeypatch):
    target, pending = tmp_path / "state.json", tmp_path / "pending"
    target.write_text("old")
    pending.write_text("new")
    calls = []
    def disk_full(*args):
        calls.append(1)
        raise OSError(28, "Disk full")
    monkeypatch.setattr(os, "replace", disk_full)
    with pytest.raises(OSError, match="Disk full"):
        replace_file(pending, target)
    assert calls == [1] and target.read_text() == "old"
