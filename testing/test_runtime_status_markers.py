"""Read-only runtime status binding, using project/legacy fixtures only."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import rs
from modules import project_runtime


@pytest.fixture
def status_case(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    workspace = project / 'proc'
    agent = workspace / '_agent'
    root = workspace / 'tmp' / 'attempt'
    markers = root / 'markers'
    markers.mkdir(parents=True)
    agent.mkdir()
    legacy = tmp_path / 'legacy'
    legacy.mkdir()
    monkeypatch.setattr(rs, 'ERRORS_DIR', str(legacy))
    monkeypatch.setattr(rs, '_pid_alive', lambda pid: False)
    monkeypatch.setattr(rs._verify_mod, 'verify_workspace', lambda path: {
        'verdict': 'ok', 'counts': {}, 'blocking': [], 'incomplete': [], 'stages': {}})
    for directory, text in ((markers, 'PROJECT_ONLY'), (legacy, 'FOREIGN_GLOBAL')):
        (directory / 'progress_OWNED.txt').write_text(text)
        (directory / 'errors_OWNED.txt').write_text(text + ' error')
        (directory / 'OWNED.lock').write_text('123')
    state = {'status': 'running', 'pid': 123, 'project_id': 'project-id', 'project_attempt_id': 'stage-attempt',
             'runtime': {'RS_RUN_ID': 'attempt', 'RS_RUNTIME_ROOT': str(root), 'RS_ERRORS_DIR': str(markers),
                         'RS_INSTANCE': 'OWNED', 'RS_CONTROL_FILE': str(root / 'control.json'),
                         'RS_EVENT_FILE': str(root / 'runtime.jsonl'), 'RS_EXECUTABLE': 'not-executed'}}
    path = agent / rs.RUN_STATE_NAME
    path.write_text(json.dumps(state))
    return SimpleNamespace(project=project, workspace=workspace, agent=agent, root=root,
                           markers=markers, legacy=legacy, state=state, path=path)


def report(case, instance='OWNED'):
    return rs.status_report(str(case.workspace), case.agent, instance)


def snapshot(folder):
    return {str(p.relative_to(folder)): p.read_bytes() for p in folder.rglob('*') if p.is_file()}


@pytest.mark.parametrize('requested', ['OWNED', 'owned', None])
def test_reads_only_matching_persisted_project_markers(status_case, requested):
    before = snapshot(status_case.project)
    result = report(status_case, requested)
    assert result['marker_source'] == 'runtime'
    assert result['instance']['name'] == 'OWNED'
    assert result['instance']['progress'] == 'PROJECT_ONLY'
    assert result['instance']['marker_root'] == str(status_case.markers)
    assert result['instance']['errors_first_line'] == 'PROJECT_ONLY error'
    assert 'FOREIGN_GLOBAL' not in rs.format_status(result)
    assert 'nothing is running' not in result['run_state']['status_note']
    assert snapshot(status_case.project) == before


@pytest.mark.parametrize('bad', ['runtime_list', 'runtime_null', 'runtime_empty', 'runtime_partial',
                               'missing_marker', 'foreign_marker', 'foreign_root', 'mismatched_id',
                               'relative', 'bad_instance', 'missing_instance', 'missing_runtime'])
def test_malformed_or_foreign_binding_is_blocked_without_global_fallback(status_case, bad, tmp_path):
    state = status_case.state
    runtime = state['runtime']
    if bad.startswith('runtime_'):
        state['runtime'] = {'runtime_list': [], 'runtime_null': None, 'runtime_empty': {},
                            'runtime_partial': {'irrelevant': 'value'}}[bad]
    elif bad == 'missing_marker':
        runtime.pop('RS_ERRORS_DIR')
    elif bad == 'foreign_marker':
        runtime['RS_ERRORS_DIR'] = str(status_case.legacy)
    elif bad == 'foreign_root':
        root = tmp_path / 'foreign' / 'proc' / 'tmp' / 'attempt'
        runtime.update(RS_RUNTIME_ROOT=str(root), RS_ERRORS_DIR=str(root / 'markers'))
    elif bad == 'mismatched_id':
        runtime['RS_RUN_ID'] = 'different-attempt'
    elif bad == 'relative':
        runtime['RS_ERRORS_DIR'] = 'markers'
    elif bad == 'bad_instance':
        runtime['RS_INSTANCE'] = '../OWNED'
    elif bad == 'missing_instance':
        runtime.pop('RS_INSTANCE')
    else:
        state.pop('runtime')
    status_case.path.write_text(json.dumps(state))
    result = report(status_case)
    assert result['verify_exit'] == 2 and result['verify']['verdict'] == 'blocked'
    assert result['instance']['marker_status'] == 'unconfirmed'
    assert result['instance']['progress'] is None and result['instance']['lock_held'] is None
    text = rs.format_status(result)
    assert 'lock: unknown' in text and 'lock: free' not in text and 'FOREIGN_GLOBAL' not in text


@pytest.mark.parametrize('payload', ['[1]', '"bad"', '{broken', '{}'])
def test_invalid_run_state_cannot_select_global_markers(status_case, payload):
    status_case.path.write_text(payload)
    result = report(status_case)
    assert result['verify_exit'] == 2
    assert result['run_state_error']
    assert result['instance']['lock_held'] is None
    assert 'unconfirmed' in rs.format_status(result)


def test_explicit_foreign_instance_refused(status_case):
    result = report(status_case, 'FOREIGN')
    assert result['verify_exit'] == 2 and result['instance']['progress'] is None
    assert 'does not match' in result['instance']['diagnostic']


def test_hardlinked_runtime_marker_refused(status_case, tmp_path):
    target = status_case.markers / 'progress_OWNED.txt'
    target.unlink()
    outside = tmp_path / 'outside.txt'
    outside.write_text('UNRELATED')
    os.link(outside, target)
    result = report(status_case)
    assert result['verify_exit'] == 2 and result['instance']['progress'] is None
    assert outside.read_text() == 'UNRELATED'


def test_hardlinked_state_cannot_select_marker_evidence(status_case, tmp_path):
    outside = tmp_path / 'other-state.json'
    outside.write_bytes(status_case.path.read_bytes())
    status_case.path.unlink()
    os.link(outside, status_case.path)
    result = report(status_case)
    assert result['verify_exit'] == 2
    assert result['instance']['progress'] is None
    assert 'hardlinked' in result['run_state_error']


def test_redirected_marker_directory_refused(status_case, monkeypatch):
    original = Path.is_junction
    monkeypatch.setattr(Path, 'is_junction', lambda path: path == status_case.markers or original(path))
    result = report(status_case)
    assert result['verify_exit'] == 2 and result['instance']['progress'] is None


def test_missing_valid_runtime_markers_do_not_fall_back_or_get_created(status_case):
    for path in status_case.markers.iterdir():
        path.unlink()
    status_case.markers.rmdir()
    result = report(status_case)
    assert result['marker_source'] == 'runtime' and result['instance']['progress'] is None
    assert not status_case.markers.exists()


def test_legacy_state_without_runtime_still_uses_legacy_markers(status_case):
    status_case.path.write_text(json.dumps({'status': 'done'}))
    result = report(status_case)
    assert result['marker_source'] == 'legacy'
    assert result['instance']['progress'] == 'FOREIGN_GLOBAL'


def test_execution_persists_exact_marker_directory(status_case, monkeypatch):
    record = {'stage': 'fixture', 'argv': ['never-executed'], 'needs_realityscan': False,
              'project_id': 'project-id', 'project_attempt_id': 'stage-attempt',
              'env': dict(status_case.state['runtime'])}
    fake = SimpleNamespace(pid=987, wait=lambda **kwargs: 0)
    monkeypatch.setattr(rs.subprocess, 'Popen', lambda *a, **kw: fake)
    monkeypatch.setattr(project_runtime, 'capture_child_identity', lambda child: {'kind': 'fixture'})
    assert rs.execute_commands([record], status_case.agent, '') == 0
    state = json.loads(status_case.path.read_text())
    assert state['runtime']['RS_ERRORS_DIR'] == str(status_case.markers)
    assert report(status_case)['instance']['progress'] == 'PROJECT_ONLY'


@pytest.fixture
def native_case(status_case, monkeypatch):
    from modules.project_workspace import ProjectDocument
    case = status_case
    project = ProjectDocument.create('NA123', 'H1234', case.project)
    inventory = project.start_stage('inventory')
    project.complete_stage('inventory', attempt_id=inventory)
    attempt = project.start_stage('navigation')
    project.save()
    case.document, case.attempt = project, attempt
    case.state.update(project_id=project.project_id, project_attempt_id=attempt,
                      label=project.project_id + '/' + attempt, stage='navigation')
    case.path.write_text(json.dumps(case.state))
    case.plan = dict(project_id=project.project_id, project_attempt_id=attempt,
                     execution_label=case.state['label'], run_state='proc/_agent/RUN_STATE.json',
                     commands=[dict(project_id=project.project_id, project_attempt_id=attempt,
                                    stage='navigation', needs_realityscan=True,
                                    env=dict(case.state['runtime']))])
    case.plan_path = case.project / 'metadata' / 'plans' / 'launch.json'
    case.plan_path.parent.mkdir(parents=True)
    case.plan_path.write_text(json.dumps(case.plan))
    # A native root must never invoke the legacy directory census.
    monkeypatch.setattr(rs._verify_mod, 'verify_workspace', lambda path: pytest.fail('legacy census used'))
    return case


def native_report(case):
    return rs.status_report(str(case.project), case.project / '_agent', None)


@pytest.mark.parametrize('relative', ['proc/_agent', 'proc/intake/token/run/_agent',
                                     'proc/workflows/selection/_agent'])
def test_native_locator_follows_bound_launch_path(native_case, relative):
    case = native_case
    path = case.project / relative / rs.RUN_STATE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(case.state))
    case.plan['run_state'] = path.relative_to(case.project).as_posix()
    case.plan_path.write_text(json.dumps(case.plan))
    # A newer, unrelated legacy journal is not a candidate.
    legacy = case.project / '_agent' / rs.RUN_STATE_NAME
    legacy.parent.mkdir()
    legacy.write_text('{"status":"done"}')
    before = snapshot(case.project)
    result = native_report(case)
    assert result['verify_exit'] == 1
    assert result['run_state_path'] == str(path)
    assert result['run_state']['project_attempt_id'] == case.attempt
    assert result['instance']['progress'] == 'PROJECT_ONLY'
    assert result['stages']['navigation'] == 'running'
    assert snapshot(case.project) == before


def test_native_no_attempts_pending_ignores_helper_probes(status_case, monkeypatch):
    from modules.project_workspace import ProjectDocument
    case = status_case
    ProjectDocument.create('NA123', 'H1234', case.project).save()
    probe = case.project / 'metadata' / 'plans' / 'unregistered-probe.json'
    probe.parent.mkdir(parents=True)
    probe.write_text('not a pipeline record')
    monkeypatch.setattr(rs._verify_mod, 'verify_workspace', lambda path: pytest.fail('legacy census used'))
    before = snapshot(case.project)
    result = native_report(case)
    assert result['verify_exit'] == 1
    assert set(result['stages'].values()) == {'pending'}
    assert all(value == 0 for value in result['verify']['counts'].values())
    assert result['run_state'] is None and result['executions'] == []
    assert result['instance']['lock_held'] is None
    assert result['marker_source'] == 'unconfirmed'
    assert 'FOREIGN_GLOBAL' not in rs.format_status(result)
    assert snapshot(case.project) == before


@pytest.mark.parametrize('bad', ['missing_plan', 'foreign_plan', 'old_attempt', 'duplicate_plan',
                               'malformed_plan', 'foreign_state', 'wrong_label', 'foreign_runtime',
                               'outside_state', 'wrong_filename', 'missing_state', 'hardlinked_plan',
                               'missing_command_binding', 'duplicate_command'])
def test_native_locator_refuses_ambiguous_or_foreign_launch_evidence(native_case, bad, tmp_path):
    case = native_case
    if bad == 'missing_plan':
        case.plan_path.unlink()
    elif bad == 'foreign_plan':
        case.plan['project_id'] = 'foreign'
    elif bad == 'old_attempt':
        case.plan['project_attempt_id'] = 'old'
    elif bad == 'duplicate_plan':
        case.plan_path.with_name('duplicate.json').write_text(json.dumps(case.plan))
    elif bad == 'malformed_plan':
        case.plan = []
    elif bad == 'foreign_state':
        case.state['project_id'] = 'foreign'
    elif bad == 'wrong_label':
        case.state['label'] = 'foreign'
    elif bad == 'foreign_runtime':
        case.state['runtime']['RS_INSTANCE'] = 'FOREIGN'
    elif bad == 'outside_state':
        case.plan['run_state'] = str(tmp_path / 'foreign' / '_agent' / rs.RUN_STATE_NAME)
    elif bad == 'wrong_filename':
        case.plan['run_state'] = 'proc/_agent/other.json'
        case.path.with_name('other.json').write_text(json.dumps(case.state))
    elif bad == 'missing_state':
        case.path.unlink()
    elif bad == 'hardlinked_plan':
        os.link(case.plan_path, tmp_path / 'alias.json')
    elif bad == 'missing_command_binding':
        case.plan['commands'][0].pop('project_attempt_id')
    elif bad == 'duplicate_command':
        case.plan['commands'] *= 2
    if bad != 'missing_plan':
        case.plan_path.write_text(json.dumps(case.plan))
    if bad != 'missing_state':
        case.path.write_text(json.dumps(case.state))
    result = native_report(case)
    assert result['verify_exit'] == 2
    assert result['run_state'] is None
    assert result['marker_source'] == 'unconfirmed'
    assert 'FOREIGN_GLOBAL' not in rs.format_status(result)


def test_native_python_navigation_does_not_read_global_markers(native_case):
    case = native_case
    case.plan['commands'][0].update(needs_realityscan=False, env={})
    case.state['runtime'] = dict.fromkeys(case.state['runtime'])
    case.plan_path.write_text(json.dumps(case.plan))
    case.path.write_text(json.dumps(case.state))
    result = native_report(case)
    assert result['verify_exit'] == 1
    assert result['run_state_path'] == str(case.path)
    assert result['instance']['lock_held'] is None
    assert result['marker_source'] == 'unconfirmed'


@pytest.mark.parametrize('payload', ['{}', '[]', 'broken'])
def test_native_invalid_document_has_no_legacy_fallback(status_case, payload):
    (status_case.project / 'project.rovscan').write_text(payload)
    result = native_report(status_case)
    assert result['verify_exit'] == 2
    assert result['run_state'] is None


def test_native_multiple_documents_refused(native_case):
    document = native_case.document.path
    document.with_name('duplicate.rovscan').write_bytes(document.read_bytes())
    assert native_report(native_case)['verify_exit'] == 2


def test_status_command_uses_native_root(native_case, capsys):
    assert rs.main(['status', '--workspace', str(native_case.project), '--json']) == 1
    result = json.loads(capsys.readouterr().out)
    assert result['run_state_path'] == str(native_case.path)


@pytest.mark.parametrize('bad', ['ownership_false', 'returncode_missing', 'release_events_missing'])
def test_native_terminal_state_requires_existing_release_oracle(native_case, monkeypatch, bad):
    case = native_case
    case.state.update(status='done', returncode=0, ownership_released=True)
    if bad == 'ownership_false':
        case.state['ownership_released'] = False
    elif bad == 'returncode_missing':
        case.state.pop('returncode')
    # No event channel exists: the real release oracle must refuse it.
    case.path.write_text(json.dumps(case.state))
    assert native_report(case)['verify_exit'] == 2


def test_native_terminal_release_uses_shared_oracle(native_case, monkeypatch):
    case = native_case
    case.state.update(status='done', returncode=0, ownership_released=True)
    case.path.write_text(json.dumps(case.state))
    observed = []
    monkeypatch.setattr(project_runtime, 'require_runtime_release', lambda record: observed.append(record))
    result = native_report(case)
    assert result['verify_exit'] == 1  # Project stage still running, not inferred complete.
    assert result['executions'][0]['ownership_released'] is True
    assert observed == case.plan['commands']


@pytest.mark.parametrize('kind', ['list', 'missing', 'hardlink'])
def test_native_invalid_state_refused(native_case, kind, tmp_path):
    if kind == 'list':
        native_case.path.write_text('[]')
    elif kind == 'missing':
        native_case.path.unlink()
    else:
        os.link(native_case.path, tmp_path / 'alias.json')
    result = native_report(native_case)
    assert result['verify_exit'] == 2
    assert result['run_state'] is None


def test_native_foreign_document_root_refused(native_case, tmp_path):
    data = native_case.document.to_dict()
    data['root'] = str(tmp_path / 'elsewhere')
    native_case.document.path.write_text(json.dumps(data))
    assert native_report(native_case)['verify_exit'] == 2


def test_native_no_attempts_does_not_create_proc_or_adopt_legacy(tmp_path, monkeypatch):
    from modules.project_workspace import ProjectDocument
    project = ProjectDocument.create('NA123', 'H1234', tmp_path / 'fresh')
    project.save()
    monkeypatch.setattr(rs._verify_mod, 'verify_workspace', lambda path: pytest.fail('legacy census used'))
    before = snapshot(project.root)
    result = rs.status_report(str(project.root), project.root / '_agent', None)
    assert result['verify_exit'] == 1
    assert result['run_state_path'] == str(project.root / 'proc' / '_agent' / rs.RUN_STATE_NAME)
    assert not (project.root / 'proc').exists()
    assert snapshot(project.root) == before


def test_explicit_charter_preserves_legacy_locator_even_with_project(native_case, monkeypatch):
    case = native_case
    monkeypatch.setattr(rs._verify_mod, 'verify_workspace', lambda path: {
        'verdict': 'ok', 'counts': {}, 'blocking': [], 'incomplete': [], 'stages': {}})
    monkeypatch.setattr(rs, '_budget_block', lambda *args: {})
    path = case.project / '_agent' / rs.RUN_STATE_NAME
    path.parent.mkdir()
    path.write_text('{"status":"done"}')
    result = rs.status_report(str(case.project), path.parent, 'OWNED', charter=SimpleNamespace())
    assert result['run_state_path'] == str(path)
    assert result['marker_source'] == 'legacy'
    assert result['instance']['progress'] == 'FOREIGN_GLOBAL'


def test_native_inprocess_inventory_needs_no_launch_record(tmp_path):
    from modules.project_workspace import ProjectDocument
    project = ProjectDocument.create('NA123', 'H1234', tmp_path / 'fresh')
    project.start_stage('inventory')
    project.save()
    result = rs.status_report(str(project.root), project.root / '_agent', None)
    assert result['verify_exit'] == 1
    assert result['stages']['inventory'] == 'running'
    assert result['executions'] == []


def test_native_shared_journal_does_not_relabel_older_attempt(native_case, monkeypatch):
    case = native_case
    project = case.document
    project.complete_stage('navigation', attempt_id=case.attempt)
    later = project.start_stage('georeference')
    project.complete_stage('georeference', attempt_id=later)
    project.save()
    state = dict(case.state, project_attempt_id=later, label=project.project_id + '/' + later,
                 stage='georeference', status='done', returncode=0, ownership_released=True)
    case.path.write_text(json.dumps(state))
    plan = dict(case.plan, project_attempt_id=later, execution_label=state['label'],
                commands=[dict(case.plan['commands'][0], project_attempt_id=later, stage='georeference')])
    case.plan_path.with_name('older-mtime-but-current.json').write_text(json.dumps(plan))
    os.utime(case.plan_path, (2_000_000_000, 2_000_000_000))
    monkeypatch.setattr(project_runtime, 'require_runtime_release', lambda record: None)
    result = native_report(case)
    assert result['verify_exit'] == 1
    assert result['run_state']['project_attempt_id'] == later
    assert [entry['stage'] for entry in result['executions']] == ['georeference']
    assert any('superseded' in text for text in result['verify']['incomplete'])


def test_native_multiple_stage_journals_are_reported_individually(native_case, monkeypatch):
    case = native_case
    project = case.document
    project.complete_stage('navigation', attempt_id=case.attempt)
    later = project.start_stage('georeference')
    project.complete_stage('georeference', attempt_id=later)
    project.save()
    case.state.update(status='done', returncode=0, ownership_released=True)
    case.path.write_text(json.dumps(case.state))
    state = dict(case.state, project_attempt_id=later, label=project.project_id + '/' + later,
                 stage='georeference')
    path = case.project / 'proc' / 'intake' / 'other' / '_agent' / rs.RUN_STATE_NAME
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(state))
    plan = dict(case.plan, project_attempt_id=later, execution_label=state['label'],
                run_state=path.relative_to(case.project).as_posix(),
                commands=[dict(case.plan['commands'][0], project_attempt_id=later, stage='georeference')])
    case.plan_path.with_name('second.json').write_text(json.dumps(plan))
    monkeypatch.setattr(project_runtime, 'require_runtime_release', lambda record: None)
    result = native_report(case)
    assert result['verify_exit'] == 1
    assert result['run_state'] is None
    assert {entry['stage'] for entry in result['executions']} == {'navigation', 'georeference'}
    assert 'run_state_path' not in result
