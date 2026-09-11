"""Deployment runtime regressions. All RS calls are mocked; locks use tmp_path.

Only the cross-process OS-lock test starts a child: the same Python interpreter
running _OSLock, never RealityScan, a workflow script, or an install operation.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from unittest.mock import Mock

import pytest

from modules.realityscan_interface import realityscan_cli as rc

_PYTHON_POPEN = subprocess.Popen


class Store:
    def __init__(self, **values):
        self.values = values

    def get(self, section, key, default=None):
        return self.values.get(key, default)


class Process:
    pid = 54321

    def __init__(self, code=0):
        self.returncode = code

    def poll(self):
        return self.returncode


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    for key in ('RS_RUN_ID', 'RS_RUNTIME_ROOT', 'RS_CONTROL_FILE', 'RS_EVENT_FILE',
                'RS_ABORT_SENTINEL', 'RS_STARTUP_REFUSED', 'RS_STARTUP_REFUSED_FILE',
                'RS_REQUIRE_NEW_INSTANCE', 'RS_BOOT_OWNED_FILE', 'RS_WORKFLOW_ID'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(rc, 'LOCKS_DIR', str(tmp_path / 'locks'))
    monkeypatch.setattr(rc, 'ERRORS_DIR', str(tmp_path / 'markers'))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'appdata'))
    monkeypatch.setattr(rc.subprocess, 'run', Mock(side_effect=AssertionError('real RS probe')))
    monkeypatch.setattr(rc.subprocess, 'Popen', Mock(side_effect=AssertionError('real workflow')))
    monkeypatch.setattr(rc, '_memory_status', lambda: None)
    monkeypatch.setattr(rc, '_available_ram_gb', lambda: None)
    monkeypatch.setattr(rc.time, 'sleep', lambda seconds: None)
    instances = []

    def make(name='RUNTIME_TEST', **settings):
        obj = rc.RealityScanCLI(logging.getLogger('runtime-test'), Store(**settings), name)
        monkeypatch.setattr(obj, 'find_executable', lambda: sys.executable)
        monkeypatch.setattr(obj, 'is_instance_running', lambda: False)
        monkeypatch.setattr(obj, 'get_instance_status', lambda instance=None: None)
        monkeypatch.setattr(obj, 'wait_for_instance_shutdown', lambda: True)
        instances.append(obj)
        return obj

    yield make
    # Cleanup only leases created by THIS fixture, including deliberately
    # unresolved test runs. Production has no force-release escape hatch.
    for obj in instances:
        for key, lease in list(obj._leases.items()):
            Path(lease.journal).write_text(json.dumps({'token': lease.token}))
            lease.retained = False
            obj._release_lock(key)
        with rc._RETAINED_GUARD:
            for run_id in obj._runs:
                rc._RETAINED_RUNS.pop(run_id, None)


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    script = tmp_path / 'Offline.bat'
    script.write_text('never executed')
    process = Process()
    def start(argv, **kwargs):
        env = kwargs['env']
        if env.get('RS_BOOT_OWNED_FILE'):
            Path(env['RS_BOOT_OWNED_FILE']).write_text(env['RS_WORKFLOW_ID'])
        return process
    spawn = Mock(side_effect=start)
    monkeypatch.setattr(rc.subprocess, 'Popen', spawn)
    return str(script), process, spawn, str(tmp_path / 'logs')


def test_named_locks_parallel_but_same_name_and_wildcards_exclusive(runtime):
    first, other, contender = runtime('A'), runtime('B'), runtime('a')
    first._acquire_lock()
    other._acquire_lock()
    with pytest.raises(RuntimeError):
        contender._acquire_lock()
    with pytest.raises(RuntimeError):
        contender._acquire_lock('*')
    assert first._release_lock()
    assert other._release_lock()
    contender._acquire_lock('*')
    with pytest.raises(RuntimeError):
        first._acquire_lock()
    assert contender._release_lock('*')


def test_os_lock_is_shared_across_processes(tmp_path):
    anchor = str(tmp_path / 'anchor')
    lock = rc._OSLock(anchor)
    code = (
        'import sys\n'
        'from modules.realityscan_interface.realityscan_cli import _OSLock\n'
        'try:\n    lock = _OSLock(sys.argv[1])\n'
        'except OSError:\n    sys.exit(0)\n'
        'sys.exit(7)\n'
    )
    try:
        child = _PYTHON_POPEN([sys.executable, '-B', '-c', code, anchor],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        out, err = child.communicate(timeout=20)
        assert child.returncode == 0, (out, err)
    finally:
        lock.close()
    # The permanent anchor remains and is reusable after OS release.
    assert Path(anchor).is_file()
    rc._OSLock(anchor).close()


def test_no_empty_publication_window(runtime, monkeypatch):
    owner, contender = runtime(), runtime()
    dump = json.dump

    def intercept(value, file, *args, **kwargs):
        with pytest.raises(RuntimeError):
            contender._acquire_lock()
        assert not contender._release_lock()
        return dump(value, file, *args, **kwargs)

    monkeypatch.setattr(rc.json, 'dump', intercept)
    owner._acquire_lock()
    assert Path(owner._lock_path()).read_text() == str(os.getpid())
    assert owner._release_lock()


def test_release_never_removes_another_owners_journal(runtime):
    owner = runtime()
    owner._acquire_lock()
    lease = owner._leases[owner.instance_name.casefold()]
    Path(lease.journal).write_text('{"token":"another-owner"}')
    assert not owner._release_lock()
    assert json.loads(Path(lease.journal).read_text())['token'] == 'another-owner'
    with pytest.raises(RuntimeError):
        runtime()._acquire_lock()


def test_unreconciled_dead_driver_journal_is_not_stale_permission(runtime):
    obj = runtime()
    Path(rc.LOCKS_DIR).mkdir()
    journal = Path(rc.LOCKS_DIR) / (obj._lease_stem(obj.instance_name) + '.owner.json')
    journal.write_text('{"pid":999999999,"token":"dead-driver"}')
    with pytest.raises(RuntimeError, match='unreconciled'):
        obj._acquire_lock()
    assert journal.exists()


def test_constructor_does_not_publish_machine_settings(runtime):
    before = dict(os.environ)
    first = runtime('A', cache_dir='C:/cacheA')
    second = runtime('B', cache_dir='D:/cacheB')
    assert dict(os.environ) == before
    assert first._machine_env['RS_CACHE_DIR'] == 'C:/cacheA'
    assert second._machine_env['RS_CACHE_DIR'] == 'D:/cacheB'
    assert second._machine_env['RS_INSTANCE'] == 'B'
    with pytest.raises(TypeError):
        first._machine_env['RS_CACHE_DIR'] = 'bad'


def test_run_env_pins_cache_but_captures_late_science_flags(runtime, workflow, monkeypatch):
    script, _, spawn, logs = workflow
    obj = runtime(cache_dir='C:/cacheA')
    monkeypatch.setenv('RS_CACHE_DIR', 'D:/other-instance')
    monkeypatch.setenv('RS_PRIOR_GROUPS_FILE', 'late-science.cmds')
    result = obj.run_batch_script(script, [], logs)
    assert result.success
    env = spawn.call_args.kwargs['env']
    assert env['RS_CACHE_DIR'] == 'C:/cacheA'
    assert env['RS_PRIOR_GROUPS_FILE'] == 'late-science.cmds'
    assert os.environ['RS_CACHE_DIR'] == 'D:/other-instance'


def test_existing_instance_refused_without_quit_or_marker_clear(runtime, workflow, monkeypatch):
    script, _, spawn, logs = workflow
    obj = runtime()
    monkeypatch.setattr(obj, 'is_instance_running', lambda: True)
    quit_instance = Mock(side_effect=AssertionError('unknown instance quit'))
    clear = Mock(side_effect=AssertionError('unknown markers cleared'))
    monkeypatch.setattr(obj, 'shutdown_instance', quit_instance)
    monkeypatch.setattr(obj, '_clear_markers', clear)
    with pytest.raises(RuntimeError, match='ownership is unknown'):
        obj.run_batch_script(script, [], logs)
    spawn.assert_not_called()
    quit_instance.assert_not_called()
    clear.assert_not_called()
    assert not obj._leases


def test_cancel_before_start_is_terminal_without_a_launch(runtime, workflow):
    script, _, spawn, logs = workflow
    control = rc.RunControl()
    assert control.request_cancel('first')
    assert not control.request_cancel('second')
    assert control.reason == 'first'
    obj = runtime()
    result = obj.run_batch_script(script, [], logs, control=control)
    assert result.status == 'cancelled' and not result.ownership_retained
    assert result.cancellation_requested and not result.success
    spawn.assert_not_called()
    assert not obj._leases


def test_requested_cancel_monitors_until_child_and_instance_are_quiet(runtime, workflow, monkeypatch):
    script, process, _, logs = workflow
    process.returncode = None
    obj, contender = runtime(), runtime()
    control, events = rc.RunControl(), []

    def observer(event):
        events.append(event)
        if event.kind == 'running':
            control.request_cancel()

    def tick(seconds):
        with pytest.raises(RuntimeError):
            contender._acquire_lock()
        process.returncode = 0

    monkeypatch.setattr(rc.time, 'sleep', tick)
    result = obj.run_batch_script(script, [], logs, control=control, observer=observer)
    assert result.status == 'cancelled' and not result.ownership_retained
    assert not result.success and result.cancellation_requested
    assert process.returncode == 0
    assert 'cancel_unconfirmed' in [e.kind for e in events]
    assert [e.sequence for e in events] == list(range(1, len(events) + 1))
    contender._acquire_lock()
    contender._release_lock()
    assert result.run_id not in rc._RETAINED_RUNS

@pytest.mark.parametrize('error', [KeyboardInterrupt(), RuntimeError('monitor failed')])
def test_interrupted_monitor_keeps_driver_alive_until_quiet(runtime, workflow, monkeypatch, error):
    script, process, _, logs = workflow
    process.returncode = None
    obj, events = runtime(), []
    monkeypatch.setattr(obj, '_monitor_until_exit', Mock(side_effect=error))
    monkeypatch.setattr(rc.subprocess, 'run', Mock(return_value=SimpleNamespace(returncode=0)))

    def tick(seconds):
        with pytest.raises(RuntimeError):
            runtime()._acquire_lock()
        process.returncode = 0

    monkeypatch.setattr(rc.time, 'sleep', tick)
    result = obj.run_batch_script(script, [], logs, observer=events.append)
    assert result.status == ('cancelled' if isinstance(error, KeyboardInterrupt) else 'failed')
    assert not result.ownership_retained and not result.success
    assert process.returncode == 0

def test_interrupt_during_spawn_is_unconfirmed_without_a_child_handle(runtime, workflow):
    script, _, spawn, logs = workflow
    spawn.side_effect = KeyboardInterrupt()
    obj = runtime()
    events = []
    with pytest.raises(KeyboardInterrupt):
        obj.run_batch_script(script, [], logs, observer=events.append)
    result = obj.reconcile_run(events[0].run_id)
    assert result.status == 'cancel_unconfirmed' and result.ownership_retained


def test_spawn_failure_releases_ownership(runtime, workflow):
    script, _, spawn, logs = workflow
    spawn.side_effect = FileNotFoundError('not started')
    obj = runtime()
    with pytest.raises(FileNotFoundError):
        obj.run_batch_script(script, [], logs)
    assert not obj._leases


def test_shutdown_failure_retains_lease_and_can_be_reconciled(runtime, workflow, monkeypatch):
    script, _, _, logs = workflow
    obj = runtime()
    monkeypatch.setattr(obj, 'wait_for_instance_shutdown', lambda: False)
    result = obj.run_batch_script(script, [], logs)
    assert result.status == 'done' and not result.ownership_retained


def test_observer_failure_is_nonfatal_and_event_payload_is_readonly(runtime, workflow):
    script, _, _, logs = workflow
    events = []

    def observer(event):
        events.append(event)
        assert json.loads(json.dumps(event.as_dict()))['run_id'] == event.run_id
        with pytest.raises(TypeError):
            event.data['mutation'] = 1
        raise ValueError('broken UI')

    assert runtime().run_batch_script(script, [], logs, observer=observer).success
    assert events[-1].kind == 'done'


def test_unique_logs_for_same_second_and_directory(runtime, workflow, monkeypatch):
    script, _, _, logs = workflow
    monkeypatch.setattr(rc.time, 'strftime', lambda *args: 'same-second')
    first = runtime('A').run_batch_script(script, [], logs)
    second = runtime('B').run_batch_script(script, [], logs)
    assert first.log_path != second.log_path
    assert first.resource_path != second.resource_path
    for path in (first.log_path, second.log_path, first.resource_path, second.resource_path):
        assert Path(path).exists()


def test_snapshot_is_bounded_and_preserves_global_log(runtime, workflow, monkeypatch, tmp_path):
    script, _, _, logs = workflow
    source = tmp_path / 'appdata' / 'Temp' / 'RealityScan.log'
    source.parent.mkdir(parents=True)
    payload = b'x' * (8 * 1024 * 1024 + 17)
    source.write_bytes(payload)
    monkeypatch.setenv('LOCALAPPDATA', str(source.parent.parent))
    events = []
    result = runtime().run_batch_script(script, [], logs, observer=events.append)
    snapshots = [e for e in events if e.kind == 'log_snapshot']
    assert result.success and len(snapshots) == 2
    for event in snapshots:
        assert Path(event.data['path']).stat().st_size == 8 * 1024 * 1024
        assert event.data['shared_global_log'] is True
    assert source.read_bytes() == payload


def _progress(alg, elapsed, fraction=.5):
    return f'{alg} {fraction:.2f} {elapsed:.2f} {elapsed*(1-fraction)/fraction:.2f} #progress'


def test_same_algorithm_elapsed_restart_starts_new_generation():
    tracker = rc._ProgressTracker()
    tracker.update(_progress(1, 40000))
    tracker.update(_progress(1, 40600))
    generation = tracker.generation
    assert tracker.update(_progress(1, 10)) is None
    assert tracker.generation == generation + 1
    assert tracker.update(_progress(1, 3610)) == 3600


def test_moving_window_not_frozen_when_endpoints_match():
    tracker = rc._ProgressTracker()
    tracker.update(_progress(1, 10, .2))
    tracker.update(_progress(1, 1810, .5))
    assert tracker.update(_progress(1, 3610, .2)) is None


@pytest.mark.parametrize('bad', ['1 0.50 nan 30 #progress', '1 0.50 30 inf #progress'])
def test_nonfinite_progress_cannot_poison_window(bad):
    assert rc.parse_progress_line(bad) is None


def test_freeze_warnings_rearm_after_recovery_and_new_generation(runtime, monkeypatch):
    obj = runtime()
    lines = [_progress(1, 10), _progress(1, 3610),
             _progress(1, 4210, .6), _progress(1, 8410, .6),
             _progress(2, 10), _progress(2, 3610)]
    process = Mock()
    process.poll.side_effect = [None] * len(lines) + [0]
    monkeypatch.setattr(obj, '_tail_line', Mock(side_effect=lines))
    monkeypatch.setattr(obj, '_read_marker', lambda *args: '')
    events = []
    run = rc._Run('test-run', 'RUNTIME_TEST', False, MappingProxyType({}),
                  rc.RunControl(), events.append)
    obj._monitor_loop(process, 'unused', '', '', rc.time.monotonic(), False,
                      False, None, None, 0, 0, {}, run=run)
    freezes = [e for e in events if e.kind == 'progress_stalled']
    assert len(freezes) == 3
    assert freezes[-1].data['generation'] == 2
    assert len([e for e in events if e.kind == 'progress_recovered']) == 2


def test_resources_sample_uses_run_cache_after_global_env_changes(runtime, monkeypatch, tmp_path):
    obj = runtime(cache_dir='C:/cacheA')
    run = rc._Run('sample', obj.instance_name, False,
                  MappingProxyType({'RS_CACHE_DIR': 'C:/cacheA'}), rc.RunControl(), None)
    monkeypatch.setenv('RS_CACHE_DIR', 'D:/wrong-cache')
    monkeypatch.setattr(rc, '_memory_status', lambda: dict(
        commit_total_gb=20, commit_avail_gb=10, ram_avail_gb=5,
        ram_total_gb=10, mem_load_pct=50))
    disk = Mock(return_value=SimpleNamespace(free=100 * 1024**3))
    monkeypatch.setattr(rc.shutil, 'disk_usage', disk)
    peak = dict(cpu_pct=0, commit_used_gb=0, ram_avail_gb_min=None,
                disk_free_gb_min=None, cache_free_gb_min=None)
    with (tmp_path / 'trace.csv').open('w') as trace:
        obj._sample_resources(trace, SimpleNamespace(percent=lambda: 1), peak, 0, '', run=run)
    assert disk.call_args_list[-1].args == ('C:/cacheA',)


def test_attach_preserves_target_argument_and_reports_unknown_cache(runtime, workflow, monkeypatch):
    script, _, spawn, logs = workflow
    obj = runtime(cache_dir='C:/owned-cache')
    monkeypatch.setattr(obj, 'get_instance_status', lambda instance=None: {'id': 'save', 'progress': '100.0%'})
    events = []
    result = obj.run_attach_script(script, ['target-model'], logs, instance='OTHER', observer=events.append)
    assert result.success
    assert spawn.call_args.args[0] == [script, 'OTHER', 'target-model']
    assert 'RS_CACHE_DIR' not in spawn.call_args.kwargs['env']
    assert [e for e in events if e.kind == 'running'][0].data['cache_dir'] is None


def test_legacy_workflowresult_positional_constructor():
    result = rc.WorkflowResult(True, 0, 'log', '', ['x'], 1.0)
    assert result.success and result.completed_processes == ['x']
    assert not result.ownership_retained


def test_terminal_observer_cannot_make_finally_release_the_next_run(runtime, workflow):
    script, _, _, logs = workflow
    obj = runtime()

    def observer(event):
        if event.kind == 'done':
            obj._acquire_lock(token='next-run')

    result = obj.run_batch_script(script, [], logs, observer=observer)
    assert result.success
    lease = obj._leases[obj.instance_name.casefold()]
    assert lease.token == 'next-run'
    with pytest.raises(RuntimeError):
        runtime()._acquire_lock()


def test_result_markers_captured_before_completion_observer(runtime, workflow, monkeypatch):
    script, _, _, logs = workflow
    obj = runtime()
    original_monitor = obj._monitor_until_exit

    def monitor(*args, **kwargs):
        Path(obj._marker('results')).write_text('original workflow result')
        return original_monitor(*args, **kwargs)

    monkeypatch.setattr(obj, '_monitor_until_exit', monitor)

    def observer(event):
        if event.kind == 'done':
            Path(obj._marker('results')).write_text('next workflow result')

    result = obj.run_batch_script(script, [], logs, observer=observer)
    assert result.completed_processes == ['original workflow result']


def test_failed_cancelled_attach_waits_while_target_exists(runtime, workflow, monkeypatch):
    script, process, _, logs = workflow
    process.returncode = None
    obj, control = runtime(), rc.RunControl()
    # Attach starts reachable; a later query failure cannot release its owner.
    states = iter([{'id': 'save'}, {'timeout': True}, None, None])
    monkeypatch.setattr(obj, 'get_instance_status', lambda instance=None: next(states))

    def observer(event):
        if event.kind == 'running':
            control.request_cancel()

    def tick(seconds):
        assert obj._leases
        process.returncode = 1

    monkeypatch.setattr(rc.time, 'sleep', tick)
    result = obj.run_attach_script(script, [], logs, instance='TARGET', control=control, observer=observer)
    assert result.status == 'cancelled' and not result.ownership_retained

def test_cancel_in_prelaunch_snapshot_does_not_launch(runtime, workflow, monkeypatch):
    script, _, spawn, logs = workflow
    obj = runtime()
    control = rc.RunControl()
    monkeypatch.setattr(obj, '_snapshot_log', lambda *args: control.request_cancel())
    result = obj.run_batch_script(script, [], logs, control=control)
    assert result.status == 'cancelled' and not result.ownership_retained
    assert not obj._leases
    spawn.assert_not_called()


def _channels(tmp_path, monkeypatch):
    root = tmp_path / 'project' / 'proc' / 'tmp' / 'attempt-123'
    root.mkdir(parents=True)
    monkeypatch.setenv('RS_RUN_ID', 'attempt-123')
    monkeypatch.setenv('RS_RUNTIME_ROOT', str(root))
    monkeypatch.setenv('RS_CONTROL_FILE', str(root / 'control.json'))
    monkeypatch.setenv('RS_EVENT_FILE', str(root / 'runtime.jsonl'))
    return root


def test_file_abort_stops_dispatch_then_reaborts_after_shell_exit(runtime, workflow, monkeypatch, tmp_path):
    root = _channels(tmp_path, monkeypatch)
    script, process, _, logs = workflow
    process.returncode = None
    obj = runtime()
    state = {'gone': False}
    calls = []

    def status(instance=None):
        return None if state['gone'] else {'id': '0xffffffff', 'progress': '0.0%',
                                           'endEstimation': '0.00sec', 'rev': 17}

    monkeypatch.setattr(obj, 'get_instance_status', status)

    def command(argv, **kwargs):
        assert obj._leases
        assert list(root.glob('abort_*.sentinel')), 'sentinel must precede abort'
        assert argv[0] == sys.executable
        calls.append(argv)
        if '-abortInstance' in argv:
            process.returncode = 1223
        elif '-quit' in argv:
            assert len([c for c in calls if '-abortInstance' in c]) == 2
            state['gone'] = True
        elif '-waitCompleted' in argv:
            pass
        else:
            pytest.fail(f'unexpected control command: {argv}')
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(rc.subprocess, 'run', command)

    def observer(event):
        if event.kind == 'running':
            (root / 'control.json').write_text(json.dumps({
                'run_id': 'attempt-123', 'mode': 'abort_current', 'requested_at': '2026-09-11T12:00:00Z'}))

    result = obj.run_batch_script(script, [], logs, observer=observer)
    assert result.status == 'cancelled' and not result.ownership_retained
    assert state['gone'] and len(calls) == 4
    events = [json.loads(line) for line in (root / 'runtime.jsonl').read_text().splitlines()]
    assert all(e['parent_run_id'] == 'attempt-123' for e in events)
    assert events[-1]['kind'] == 'cancelled'
    assert any(e['kind'] == 'dispatch_stopped' for e in events)
    assert list(root.glob('abort_*.sentinel')), 'sentinel remains sticky after completion'


@pytest.mark.parametrize('control_payload', [
    {'run_id': 'another-run', 'mode': 'abort_current', 'requested_at': 123},
    {'run_id': 'attempt-123', 'mode': 'kill_everything', 'requested_at': 123},
    {'run_id': 'attempt-123', 'mode': 'abort_current'},
    {'run_id': 'attempt-123', 'mode': 'abort_current', 'requested_at': '2026-09-11'},
    [],
])
def test_invalid_file_control_never_aborts(runtime, workflow, monkeypatch, tmp_path, control_payload):
    root = _channels(tmp_path, monkeypatch)
    (root / 'control.json').write_text(json.dumps(control_payload))
    script, _, _, logs = workflow
    result = runtime().run_batch_script(script, [], logs)
    assert result.success and not result.cancellation_requested
    rc.subprocess.run.assert_not_called()
    assert not list(root.glob('abort_*.sentinel'))
    events = [json.loads(line) for line in (root / 'runtime.jsonl').read_text().splitlines()]
    assert len([event for event in events if event['kind'] == 'control_rejected']) == 1


def test_file_after_step_does_not_fail_child_workflow(runtime, workflow, monkeypatch, tmp_path):
    root = _channels(tmp_path, monkeypatch)
    (root / 'control.json').write_text(json.dumps({
        'run_id': 'attempt-123', 'mode': 'after_step', 'requested_at': 123.0}))
    script, _, spawn, logs = workflow
    result = runtime().run_batch_script(script, [], logs)
    assert result.status == 'done' and not result.ownership_retained
    assert result.success and not result.cancellation_requested
    spawn.assert_called_once()
    assert not list(root.glob('abort_*.sentinel'))


@pytest.mark.parametrize('invalid', ['root', 'escape', 'alias'])
def test_channel_paths_must_be_scoped_to_attempt(runtime, workflow, monkeypatch, tmp_path, invalid):
    root = _channels(tmp_path, monkeypatch)
    if invalid == 'root':
        monkeypatch.setenv('RS_RUNTIME_ROOT', str(tmp_path))
    elif invalid == 'escape':
        monkeypatch.setenv('RS_CONTROL_FILE', str(root / '..' / 'outside.json'))
    else:
        monkeypatch.setenv('RS_EVENT_FILE', str(root / 'control.json'))
    script, _, spawn, logs = workflow
    with pytest.raises(ValueError):
        runtime().run_batch_script(script, [], logs)
    spawn.assert_not_called()


def test_abort_refused_for_borrowed_instance(runtime, workflow, monkeypatch):
    script, process, _, logs = workflow
    process.returncode = None
    obj, control, events = runtime(), rc.RunControl(), []
    monkeypatch.setattr(obj, 'get_instance_status', lambda instance=None: {'id': 'save', 'progress': '100%', 'rev': 1})

    def observer(event):
        events.append(event)
        if event.kind == 'running':
            control.request_cancel(mode='abort_current')

    monkeypatch.setattr(rc.time, 'sleep', lambda seconds: setattr(process, 'returncode', 0))
    result = obj.run_attach_script(script, [], logs, instance='BORROWED', control=control, observer=observer)
    assert result.status == 'cancelled' and not result.ownership_retained
    assert any(event.kind == 'abort_refused' for event in events)
    rc.subprocess.run.assert_not_called()


def test_every_owned_script_mutating_dispatch_has_sticky_guard():
    scripts = Path(rc.SCRIPTS_DIR)
    for script in scripts.glob('*.bat'):
        if script.name == 'RuntimeAbortGuard.bat':
            continue
        raw = script.read_bytes()
        assert b'\n' not in raw.replace(b'\r\n', b''), script.name
        lines = raw.decode('utf-8').splitlines()
        for i, line in enumerate(lines):
            if line.lstrip().lower().startswith(('::', 'rem ')):
                continue
            if (re.search(r'%RealityScan%.*(?:-delegateTo|-setInstanceName)', line, re.I)
                    or re.search(r'^\s*call\s+.*startRealityScan\.bat', line, re.I)):
                assert 'RuntimeAbortGuard.bat' in lines[i - 1], (script.name, i + 1)


@pytest.mark.skipif(os.name != 'nt', reason='native cmd guard behavior')
@pytest.mark.parametrize('requested', [False, True])
def test_native_batch_guard_obeys_sticky_sentinel(tmp_path, requested):
    sentinel = tmp_path / 'abort.sentinel'
    if requested:
        sentinel.write_text('validated owned request')
    guard = str(Path(rc.SCRIPTS_DIR) / 'RuntimeAbortGuard.bat')
    child = _PYTHON_POPEN([os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c', guard],
                          env={**os.environ, 'RS_ABORT_SENTINEL': str(sentinel)},
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          creationflags=rc._NO_WINDOW)
    out, err = child.communicate(timeout=10)
    assert child.returncode == (1223 if requested else 0), (out, err)
    assert sentinel.exists() == requested


def test_late_startup_conflict_never_aborts_or_waits_for_foreign_instance(runtime, workflow, monkeypatch):
    script, process, spawn, logs = workflow
    obj = runtime()

    def refused(argv, **kwargs):
        env = kwargs['env']
        Path(env['RS_STARTUP_REFUSED_FILE']).write_text('late existing instance')
        process.returncode = 1223
        return process

    spawn.side_effect = refused
    monkeypatch.setattr(obj, 'wait_for_instance_shutdown', Mock(side_effect=AssertionError('foreign shutdown wait')))
    result = obj.run_batch_script(script, [], logs)
    assert result.status == 'failed' and 'ownership conflict' in result.errors
    assert not obj._leases
    rc.subprocess.run.assert_not_called()


@pytest.mark.skipif(os.name != 'nt', reason='native startup guard behavior')
def test_native_startup_refuses_a_late_existing_instance_without_reset(tmp_path):
    fake = tmp_path / 'FakeStatus.bat'
    calls = tmp_path / 'calls.txt'
    fake.write_bytes(('@echo off\r\n>>"' + str(calls) + '" echo %*\r\nexit /b 0\r\n').encode('ascii'))
    refused = tmp_path / 'refused.txt'
    startup = str(Path(rc.SCRIPTS_DIR) / 'startRealityScan.bat')
    child = _PYTHON_POPEN([os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c', startup],
                          env={**os.environ, 'RealityScan': 'call "' + str(fake) + '"',
                               'RS_INSTANCE': 'SYNTHETIC_TEST', 'RS_REQUIRE_NEW_INSTANCE': '1',
                               'RS_STARTUP_REFUSED_FILE': str(refused)},
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          creationflags=rc._NO_WINDOW)
    out, err = child.communicate(timeout=10)
    assert child.returncode == 1223, (out, err)
    assert refused.exists()
    assert calls.read_text().strip() == '-getStatus SYNTHETIC_TEST'


def test_owned_control_refuses_missing_or_foreign_boot_proof(runtime, tmp_path):
    obj = runtime()
    obj._acquire_lock(token='workflow')
    proof = tmp_path / 'proof'
    run = rc._Run('workflow', obj.instance_name, False,
                  MappingProxyType({'RS_EXECUTABLE': 'never-run'}), rc.RunControl(), None)
    run.process = Process()
    run.boot_owned_file = str(proof)
    with pytest.raises(RuntimeError, match='owned boot provenance'):
        obj._owned_control(run, '-abortInstance')
    proof.write_text('different-workflow')
    with pytest.raises(RuntimeError, match='owned boot provenance'):
        obj._owned_control(run, '-abortInstance')
    rc.subprocess.run.assert_not_called()


def test_reconcile_cannot_release_a_run_still_owned_by_monitor(runtime, tmp_path):
    obj = runtime()
    obj._acquire_lock(token='active')
    run = rc._Run('active', obj.instance_name, False, MappingProxyType({}), rc.RunControl(), None)
    run.process = Process(0)
    obj._retain_run(run, 'shutdown_unconfirmed', 'still monitored')
    result = obj.reconcile_run('active')
    assert result.ownership_retained
    assert obj._leases[obj.instance_name.casefold()].retained


@pytest.mark.skipif(os.name != 'nt', reason='native cmd errorlevel preservation')
@pytest.mark.parametrize('incoming', [0, 1])
def test_dispatch_guard_preserves_conditional_settings_selection(tmp_path, incoming):
    script = tmp_path / 'conditional.bat'
    output = tmp_path / 'dispatched.txt'
    guard = str(Path(rc.SCRIPTS_DIR) / 'RuntimeAbortGuard.bat')
    script.write_bytes((
        '@echo off\r\n'
        f'cmd /c exit {incoming}\r\n'
        'if not errorlevel 1 (\r\n'
        f'    call "{guard}" || exit /b 1223\r\n'
        f'    >"{output}" echo dispatched\r\n'
        ')\r\nexit /b 0\r\n').encode('ascii'))
    env = dict(os.environ)
    for key in ('RS_ABORT_SENTINEL', 'RS_STARTUP_REFUSED', 'RS_STARTUP_REFUSED_FILE'):
        env.pop(key, None)
    child = _PYTHON_POPEN([os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c', str(script)],
                          env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          creationflags=rc._NO_WINDOW)
    out, err = child.communicate(timeout=10)
    assert child.returncode == 0, (out, err)
    assert output.exists() == (incoming == 0)


def test_abort_timeout_and_changing_idle_revision_cannot_release_early(runtime, workflow, monkeypatch):
    script, process, _, logs = workflow
    process.returncode = None
    obj, control, events = runtime(), rc.RunControl(), []
    state = {'aborts': 0, 'quit': False, 'observations': 0}
    observations = iter([
        {'progress': '0%', 'rev': 1},
        {'progress': '0%', 'rev': 1},
        {'id': '0xffffffff', 'progress': '0%', 'endEstimation': '0sec', 'rev': 2},
        {'id': '0xffffffff', 'progress': '0%', 'endEstimation': '0sec', 'rev': 3},
        {'id': '0xffffffff', 'progress': '0%', 'endEstimation': '0sec', 'rev': 3},
    ])

    def status(instance=None):
        state['observations'] += 1
        if state['quit']:
            return None
        return next(observations)

    def command(argv, **kwargs):
        assert obj._leases
        if '-abortInstance' in argv:
            state['aborts'] += 1
            process.returncode = 1223
            if state['aborts'] == 1:
                raise subprocess.TimeoutExpired(argv, 1)
        elif '-quit' in argv:
            assert state['observations'] >= 5
            state['quit'] = True
        return SimpleNamespace(returncode=0)

    def observer(event):
        events.append(event)
        if event.kind == 'running':
            control.request_cancel(mode='abort_current')

    monkeypatch.setattr(obj, 'get_instance_status', status)
    monkeypatch.setattr(rc.subprocess, 'run', command)
    result = obj.run_batch_script(script, [], logs, control=control, observer=observer)
    assert result.status == 'cancelled' and state['quit'] and state['aborts'] == 2
    assert any(event.kind == 'abort_unconfirmed' for event in events)
    assert not result.ownership_retained
