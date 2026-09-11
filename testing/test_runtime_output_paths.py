"""Project runtime outputs stay outside a read-only application checkout."""
import hashlib
import os
from pathlib import Path
import subprocess

import pytest

from modules.realityscan_interface import realityscan_cli as rc
from testing.test_runtime_deployment import runtime, workflow, _PYTHON_POPEN  # noqa: F401


def configure(tmp_path, monkeypatch, name='attempt'):
    root = tmp_path / 'project' / 'proc' / 'tmp' / name
    monkeypatch.setenv('RS_RUN_ID', name)
    monkeypatch.setenv('RS_RUNTIME_ROOT', str(root))
    monkeypatch.setenv('RS_ERRORS_DIR', str(root / 'markers'))
    return root


def test_markers_context_frozen_per_cli_and_global_ownership_still_shared(runtime, tmp_path, monkeypatch):
    first_root = configure(tmp_path, monkeypatch, 'first')
    first = runtime('INSTANCE')
    second_root = configure(tmp_path, monkeypatch, 'second')
    second = runtime('INSTANCE')
    assert Path(first._marker('progress')).parent == first_root / 'markers'
    assert Path(first._lock_path()).parent == first_root / 'markers'
    assert Path(second._marker('errors')).parent == second_root / 'markers'
    first._acquire_lock()
    with pytest.raises(RuntimeError):
        second._acquire_lock()
    assert first._release_lock()
    second._acquire_lock()
    assert second._release_lock()


def test_helpers_are_exact_copies_and_clear_only_own_markers(runtime, tmp_path, monkeypatch):
    root = configure(tmp_path, monkeypatch)
    obj = runtime()
    original_dir = Path(rc.ERRORS_DIR)
    original_dir.mkdir()
    original = original_dir / 'errors_RUNTIME_TEST.txt'
    original.write_text('legacy evidence')
    hashes = obj._prepare_runtime_paths()
    for name, digest in hashes.items():
        assert (root / 'markers' / name).read_bytes() == (Path(rc.ERROR_HELPERS_DIR) / name).read_bytes()
        assert digest == hashlib.sha256((root / 'markers' / name).read_bytes()).hexdigest()
    assert (root / 'models').is_dir()
    Path(obj._marker('errors')).write_text('own old error')
    obj._clear_markers()
    assert not Path(obj._marker('errors')).exists()
    assert original.read_text() == 'legacy evidence'
    assert obj._prepare_runtime_paths() == hashes


@pytest.mark.parametrize('damage', ['different', 'hardlink'])
def test_existing_helper_drift_or_alias_refused_without_overwrite(runtime, tmp_path, monkeypatch, damage):
    root = configure(tmp_path, monkeypatch)
    marker = root / 'markers'
    marker.mkdir(parents=True)
    target = marker / 'ErrorWriter.bat'
    if damage == 'hardlink':
        origin = tmp_path / 'unrelated.bat'
        origin.write_text('unrelated')
        os.link(origin, target)
    else:
        target.write_text('unrelated')
    before = target.read_bytes()
    with pytest.raises(ValueError):
        runtime()._prepare_runtime_paths()
    assert target.read_bytes() == before


@pytest.mark.parametrize('change', ['outside', 'missing_root', 'relative', 'wrong_attempt', 'not_proc_tmp'])
def test_marker_contract_rejects_invalid_paths_before_creation(runtime, tmp_path, monkeypatch, change):
    root = configure(tmp_path, monkeypatch)
    if change == 'outside':
        monkeypatch.setenv('RS_ERRORS_DIR', str(tmp_path / 'outside'))
    elif change == 'missing_root':
        monkeypatch.delenv('RS_RUNTIME_ROOT')
    elif change == 'relative':
        monkeypatch.setenv('RS_RUNTIME_ROOT', 'relative/attempt')
    elif change == 'wrong_attempt':
        monkeypatch.setenv('RS_RUN_ID', 'another')
    else:
        monkeypatch.setenv('RS_RUNTIME_ROOT', str(tmp_path / 'attempt'))
    with pytest.raises(ValueError):
        runtime()
    assert not root.exists()


def test_run_passes_frozen_marker_paths_and_helper_hashes(runtime, workflow, tmp_path, monkeypatch):
    root = configure(tmp_path, monkeypatch)
    obj = runtime()
    configure(tmp_path, monkeypatch, 'unrelated')
    script, _, spawn, logs = workflow
    events = []
    result = obj.run_batch_script(script, [], logs, observer=events.append)
    assert result.success
    env = spawn.call_args.kwargs['env']
    assert env['RS_ERRORS_DIR'] == str(root / 'markers')
    assert env['RS_RUNTIME_ROOT'] == str(root)
    verified = [event for event in events if event.kind == 'runtime_helpers_verified']
    assert len(verified) == 1 and len(verified[0].data['sha256']) == 2


def test_legacy_without_runtime_root_keeps_existing_marker_location(runtime):
    obj = runtime()
    assert Path(obj._marker('errors')).parent == Path(rc.ERRORS_DIR)
    assert obj._prepare_runtime_paths() == {}


@pytest.mark.skipif(os.name != 'nt', reason='Native Windows batch variable contract')
def test_setvariables_native_uses_staged_paths_without_repo_outputs(runtime, tmp_path, monkeypatch):
    root = configure(tmp_path, monkeypatch)
    obj = runtime()
    obj._prepare_runtime_paths()
    source = Path(rc.SCRIPTS_DIR) / 'SetVariables.bat'
    # Read-only application clone: no Errors or Models directories exist here.
    install = tmp_path / 'read only app' / 'Scripts'
    install.mkdir(parents=True)
    (install / 'SetVariables.bat').write_bytes(source.read_bytes())
    wrapper = tmp_path / 'show_vars.bat'
    wrapper.write_bytes((f'@echo off\r\ncall "{install / "SetVariables.bat"}"\r\n'
                         'if errorlevel 1 exit /b 1\r\necho ERRORS=%ErrorPath%\r\n'
                         'echo MODELS=%Models%\r\n').encode())
    env = dict(os.environ, RS_EXECUTABLE='C:/not-run/RealityScan.exe')
    child = _PYTHON_POPEN([str(wrapper)], env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, creationflags=rc._NO_WINDOW)
    out, err = child.communicate(timeout=10)
    assert child.returncode == 0, (out, err)
    output = out.decode()
    assert f'ERRORS={root / "markers"}' in output
    assert f'MODELS={root / "models"}' in output
    assert not (install.parent / 'Errors').exists()
    assert not (install.parent / 'Models').exists()
    assert b'\n' not in source.read_bytes().replace(b'\r\n', b'')
