"""Offline regression tests for failed-batch cleanup and reviewed recovery."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules import project_runtime
from modules.realityscan_interface import realityscan_cli as rc
from testing.test_runtime_deployment import runtime, workflow  # noqa: F401


def idle(rev=17):
    return {'id': '0xffffffff', 'progress': '0.0%', 'endEstimation': '0.00sec',
            'rev': rev, 'lastError': -2147467259}


@pytest.mark.parametrize('wait_code', [0, 1, 2147500037])
def test_failed_owned_batch_cleans_up_immediately_and_stays_failed(runtime, workflow, monkeypatch, wait_code):
    script, process, _, logs = workflow
    process.returncode = 1
    obj = runtime()
    state, calls = {'gone': False}, []
    monkeypatch.setattr(obj, 'get_instance_status', lambda instance=None:
                        None if state['gone'] else idle())
    monkeypatch.setattr(obj, 'wait_for_instance_shutdown', lambda: pytest.fail('passive shutdown wait'))
    def send(argv, **kwargs):
        assert obj._leases, 'cleanup must retain original lease'
        calls.append(argv)
        if '-quit' in argv:
            state['gone'] = True
        return SimpleNamespace(returncode=wait_code if '-waitCompleted' in argv else 0)
    monkeypatch.setattr(rc.subprocess, 'run', send)
    events = []
    result = obj.run_batch_script(script, [], logs, observer=events.append)
    assert result.status == 'failed' and result.return_code == 1
    assert not result.cancellation_requested and not result.ownership_retained
    assert len(calls) == 4 and '-waitCompleted' in calls[-2] and '-quit' in calls[-1]
    assert events[-1].kind == 'failed'
    assert any(event.kind == 'failure_cleanup_requested' for event in events)
    wait_event = next(event for event in events if event.kind == 'abort_wait_completed')
    assert wait_event.data['client']['return_code'] == wait_code
    assert wait_event.data['diagnostic_only']


def test_failed_batch_already_absent_needs_no_control(runtime, workflow):
    script, process, _, logs = workflow
    process.returncode = 1
    result = runtime().run_batch_script(script, [], logs)
    assert result.status == 'failed' and not result.ownership_retained
    rc.subprocess.run.assert_not_called()


@pytest.mark.parametrize('mode', ['attach', 'no_receipt', 'startup_refused'])
def test_failure_does_not_authorize_foreign_control(runtime, workflow, monkeypatch, mode):
    script, process, spawn, logs = workflow
    process.returncode = 1
    obj = runtime()
    if mode == 'attach':
        monkeypatch.setattr(obj, 'get_instance_status', lambda instance=None: {'id': 'save', 'lastError': 42})
        result = obj.run_attach_script(script, [], logs, instance=obj.instance_name)
    else:
        original = spawn.side_effect
        def start(argv, **kwargs):
            child = original(argv, **kwargs)
            path = kwargs['env']['RS_BOOT_OWNED_FILE']
            if mode == 'no_receipt':
                Path(path).unlink()
            else:
                Path(kwargs['env']['RS_STARTUP_REFUSED_FILE']).write_text('foreign')
            return child
        spawn.side_effect = start
        result = obj.run_batch_script(script, [], logs)
    assert result.status == 'failed'
    rc.subprocess.run.assert_not_called()


@pytest.mark.parametrize('case,absent', [
    ('empty', True), ('same_name', False), ('other_name', True), ('unnamed', False),
    ('query_helper', True), ('unreadable', False), ('census_failure', False),
])
def test_negative_cli_result_needs_independent_complete_census(runtime, monkeypatch, case, absent):
    obj = runtime('OWNED')
    rows = [] if case == 'empty' else [{'Name': 'RealityScan.exe', 'argv': {
        'same_name': ['rs', '-setInstanceName', 'OWNED'],
        'other_name': ['rs', '-setInstanceName', 'OTHER'],
        'unnamed': ['rs'], 'query_helper': ['rs', '-getStatus', 'OWNED'],
    }.get(case)}]
    def census():
        if case == 'census_failure':
            raise OSError('access denied')
        return rows
    def argv(row):
        if row['argv'] is None:
            raise OSError('command line unreadable')
        return row['argv']
    monkeypatch.setattr(obj, '_process_inventory', census)
    monkeypatch.setattr(obj, '_process_argv', argv)
    monkeypatch.setattr(rc.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=1))
    result = rc.RealityScanCLI.get_instance_status(obj)
    assert (result is None) == absent
    if not absent:
        assert result['unconfirmed']


@pytest.mark.parametrize('failure', ['oserror', 'timeout', 'empty_success'])
def test_status_failure_never_proves_release(runtime, monkeypatch, failure):
    obj = runtime()
    def query(*args, **kwargs):
        if failure == 'oserror':
            raise OSError('query failed')
        if failure == 'timeout':
            raise rc.subprocess.TimeoutExpired('query', 60)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(rc.subprocess, 'run', query)
    assert rc.RealityScanCLI.get_instance_status(obj)['unconfirmed']


@pytest.fixture
def recovery(runtime, tmp_path, monkeypatch):
    owner, helper = runtime('RECOVERY'), runtime('RECOVERY')
    token = 'a' * 32
    owner._acquire_lock(token=token)
    journal = Path(owner._leases['recovery'].journal)
    logs = tmp_path / 'project' / 'proc' / 'tmp' / 'attempt' / 'logs'
    logs.mkdir(parents=True)
    boot = logs / f'abort_{token}.sentinel.boot-owned'
    boot.write_text(token)
    stamp = lambda path: path.stat().st_mtime_ns // 100 + 116444736000000000
    identities = {
        os.getpid(): dict(schema=1, kind='windows_process', pid=os.getpid(), host='fixture',
                         image_path=helper.find_executable(), created_filetime=stamp(journal) - 10000000),
        777: dict(schema=1, kind='windows_process', pid=777, host='fixture',
                  image_path=helper.find_executable(), created_filetime=stamp(boot)),
    }
    rows = [{'ProcessId': 777, 'ParentProcessId': 888, 'Name': 'RealityScan.exe',
             'argv': ['rs', '-setInstanceName', 'RECOVERY']},
            {'ProcessId': os.getpid(), 'ParentProcessId': 0, 'Name': 'python.exe', 'argv': ['python']}]
    monkeypatch.setattr(helper, '_process_inventory', lambda: rows)
    monkeypatch.setattr(helper, '_process_argv', lambda row: row['argv'])
    monkeypatch.setattr(project_runtime, '_windows_process_snapshot',
                        lambda pid: {'status': 'running', 'identity': dict(identities[pid])})
    return SimpleNamespace(owner=owner, helper=helper, token=token, logs=logs, journal=journal,
                           boot=boot, rows=rows, identities=identities)


def proposal(fixture):
    return fixture.helper.inspect_owned_recovery(fixture.token, str(fixture.logs), instance_pid=777)


def test_recovery_inspection_readonly_and_creates_no_lease(recovery):
    before = {p.name: p.read_bytes() for p in recovery.logs.iterdir()}
    result = proposal(recovery)
    assert result['owner']['pid'] == os.getpid() and result['process']['pid'] == 777
    assert recovery.helper._leases == {}
    assert {p.name: p.read_bytes() for p in recovery.logs.iterdir()} == before
    rc.subprocess.run.assert_not_called()


@pytest.mark.parametrize('change', ['token', 'boot', 'active_batch', 'active_child', 'other_instance',
                                   'duplicate_instance', 'replaced_owner', 'replaced_rs', 'startup_refused'])
def test_recovery_refuses_insufficient_ownership(recovery, change):
    if change == 'token':
        recovery.journal.write_text(json.dumps({'token': 'b' * 32, 'pid': os.getpid(), 'instance': 'RECOVERY'}))
    elif change == 'boot':
        recovery.boot.write_text('b' * 32)
    elif change == 'active_batch':
        recovery.rows.append({'ProcessId': 888, 'ParentProcessId': os.getpid(), 'Name': 'cmd.exe', 'argv': ['cmd']})
    elif change == 'active_child':
        recovery.rows.append({'ProcessId': 889, 'ParentProcessId': os.getpid(), 'Name': 'python.exe', 'argv': ['python']})
    elif change == 'other_instance':
        recovery.rows[0]['argv'][-1] = 'FOREIGN'
    elif change == 'duplicate_instance':
        recovery.rows.append(dict(recovery.rows[0], ProcessId=999))
    elif change == 'replaced_owner':
        recovery.identities[os.getpid()]['created_filetime'] += 1000000000
    elif change == 'replaced_rs':
        recovery.identities[777]['created_filetime'] += 1000000000
    else:
        Path(str(recovery.boot).replace('.boot-owned', '.startup-refused')).write_text('foreign')
    with pytest.raises(ValueError):
        proposal(recovery)
    assert not recovery.helper._leases
    rc.subprocess.run.assert_not_called()


@pytest.mark.parametrize('wait_result', [0, 1, 2147500037, 'timeout'])
def test_reviewed_recovery_uses_canonical_commands_and_preserves_original_journal(recovery, monkeypatch, wait_result):
    plan = proposal(recovery)
    journal_before = recovery.journal.read_bytes()
    states = iter([idle(3), idle(3), None])
    monkeypatch.setattr(recovery.helper, 'get_instance_status', lambda *a: next(states))
    monkeypatch.setattr(project_runtime, 'inspect_owned_process', lambda identity: {'confirmed_not_running': True})
    calls = []
    def send(argv, **kwargs):
        assert recovery.owner._leases and not recovery.helper._leases
        assert Path(plan['sentinel']).read_text().strip() == recovery.token
        calls.append(argv)
        if '-waitCompleted' in argv:
            if wait_result == 'timeout':
                raise rc.subprocess.TimeoutExpired(argv, 60)
            return SimpleNamespace(returncode=wait_result)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(rc.subprocess, 'run', send)
    result = recovery.helper.recover_owned_failure(plan, approved_recovery_id=plan['recovery_id'])
    assert result['instance_absent'] and len(calls) == 3
    assert calls[0][1:] == ['-abortInstance', 'RECOVERY']
    assert calls[1][1:] == ['-waitCompleted', 'RECOVERY']
    assert calls[2][1:] == ['-delegateTo', 'RECOVERY', '-quit']
    evidence = [json.loads(line) for line in Path(result['evidence_path']).read_text().splitlines()]
    assert [event['kind'] for event in evidence] == [
        'abort_requested', 'abort_acknowledged', 'wait_completed', 'post_barrier_status',
        'post_barrier_status', 'quit_requested', 'reconciled']
    assert recovery.journal.read_bytes() == journal_before
    assert recovery.owner._leases and not recovery.helper._leases
    if wait_result == 'timeout':
        assert result['barrier']['timed_out'] and result['barrier']['return_code'] is None
    else:
        assert result['barrier']['return_code'] == wait_result


@pytest.mark.parametrize('case', ['unapproved', 'stale', 'busy', 'unknown', 'changed_before_quit'])
def test_recovery_never_quits_without_current_approval_and_idle_evidence(recovery, monkeypatch, case):
    plan = proposal(recovery)
    calls = []
    def send(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(rc.subprocess, 'run', send)
    if case == 'stale':
        plan['workflow_pid'] += 1
    states = {'busy': {'progress': '20%', 'rev': 2}, 'unknown': {'unconfirmed': True}}
    count = 0
    def status(*args):
        nonlocal count
        count += 1
        if case == 'changed_before_quit' and count == 2:
            recovery.identities[777]['created_filetime'] += 1000000000
        return states.get(case, idle(2))
    monkeypatch.setattr(recovery.helper, 'get_instance_status', status)
    if case in ('unapproved', 'stale', 'changed_before_quit'):
        with pytest.raises(ValueError):
            recovery.helper.recover_owned_failure(plan, approved_recovery_id='' if case == 'unapproved' else plan['recovery_id'])
    else:
        result = recovery.helper.recover_owned_failure(plan, approved_recovery_id=plan['recovery_id'])
        assert result['status'] == 'unconfirmed'
    assert all('-quit' not in argv for argv in calls)
    assert recovery.journal.exists() and recovery.owner._leases


@pytest.mark.parametrize('override', [
    {'id': '0x10001'}, {'id': ''}, {'progress': '100%'}, {'progress': 'nan'},
    {'endEstimation': '0.5sec'}, {'endEstimation': ''}, {'rev': True},
    {'unconfirmed': True}, {'timeout': True},
])
def test_idle_requires_exact_post_abort_sentinel_contract(override):
    assert rc.RealityScanCLI._idle_revision(idle() | override, abort_acknowledged=True) is None


def test_idle_sentinel_alone_does_not_authorize_quit():
    assert rc.RealityScanCLI._idle_revision(idle(), abort_acknowledged=False) is None
    assert rc.RealityScanCLI._idle_revision(idle(), abort_acknowledged=True) == 17


@pytest.mark.parametrize('failure', ['nonzero', 'timeout'])
def test_barrier_result_alone_cannot_quit_a_busy_instance(recovery, monkeypatch, failure):
    plan = proposal(recovery)
    calls = []
    def send(argv, **kwargs):
        calls.append(argv)
        if '-waitCompleted' in argv:
            if failure == 'timeout':
                raise rc.subprocess.TimeoutExpired(argv, 60)
            return SimpleNamespace(returncode=1)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(rc.subprocess, 'run', send)
    monkeypatch.setattr(recovery.helper, 'get_instance_status', lambda *a:
                        {'id': '0x10001', 'progress': '0%', 'endEstimation': '0sec', 'rev': 4})
    result = recovery.helper.recover_owned_failure(plan, approved_recovery_id=plan['recovery_id'])
    assert result['status'] == 'unconfirmed' and len(calls) == 2
    assert all('-quit' not in argv for argv in calls)


@pytest.mark.parametrize('states', [
    [idle(4), idle(5), idle(6)],
    [idle(4), {'unconfirmed': True}, idle(4)],
    [idle(4), idle(4) | {'id': '0x10001'}, idle(4)],
])
def test_nonzero_wait_needs_two_consecutive_identical_idle_revisions(recovery, monkeypatch, states):
    plan = proposal(recovery)
    observations, calls = iter(states), []
    monkeypatch.setattr(recovery.helper, 'get_instance_status', lambda *a: next(observations))
    def send(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=1 if '-waitCompleted' in argv else 0)
    monkeypatch.setattr(rc.subprocess, 'run', send)
    result = recovery.helper.recover_owned_failure(plan, approved_recovery_id=plan['recovery_id'])
    assert result['status'] == 'unconfirmed'
    assert all('-quit' not in argv for argv in calls)
    assert recovery.journal.exists()


def test_idle_does_not_replace_acknowledged_abort(recovery, monkeypatch):
    plan = proposal(recovery)
    monkeypatch.setattr(recovery.helper, 'get_instance_status', lambda *a: idle(4))
    calls = []
    def send(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr(rc.subprocess, 'run', send)
    result = recovery.helper.recover_owned_failure(plan, approved_recovery_id=plan['recovery_id'])
    assert result['status'] == 'unconfirmed'
    assert len(calls) == 1 and '-abortInstance' in calls[0]
    assert recovery.journal.exists()


@pytest.mark.parametrize('code', [0, 2147500037, -2147467259])
def test_diagnostic_records_exact_client_result_without_abort_or_quit(recovery, monkeypatch, code):
    plan = proposal(recovery)
    states = iter([idle(4), idle(4), idle(4)])
    monkeypatch.setattr(recovery.helper, 'get_instance_status', lambda *a: next(states))
    calls = []
    def send(argv, **kwargs):
        calls.append(argv)
        kwargs['stdout'].write('prior operation failed\n'.encode('utf-16-le'))
        return SimpleNamespace(returncode=code)
    monkeypatch.setattr(rc.subprocess, 'run', send)
    before = recovery.journal.read_bytes()
    result = recovery.helper.diagnose_owned_barrier(plan)
    assert calls == [[plan['executable'], '-waitCompleted', plan['instance']]]
    assert result['barrier']['return_code'] == code
    assert result['barrier']['output'] == 'prior operation failed\n'
    assert result['after'] == [idle(4), idle(4)]
    assert not result['mutating_commands_sent']
    assert recovery.journal.read_bytes() == before
    assert not Path(plan['sentinel']).exists()


def test_diagnostic_records_client_timeout_and_still_observes_status(recovery, monkeypatch):
    plan = proposal(recovery)
    monkeypatch.setattr(recovery.helper, 'get_instance_status', lambda *a: idle(4))
    def send(argv, **kwargs):
        kwargs['stdout'].write(b'waiting')
        raise rc.subprocess.TimeoutExpired(argv, 60)
    monkeypatch.setattr(rc.subprocess, 'run', send)
    result = recovery.helper.diagnose_owned_barrier(plan)
    assert result['barrier']['timed_out'] and result['barrier']['return_code'] is None
    assert result['barrier']['output'] == 'waiting'
    assert len(result['after']) == 2
