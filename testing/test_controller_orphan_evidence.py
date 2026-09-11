"""Controller integration contracts with offline executor/science leaves."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import rs
from modules import orphan_import_evidence, preflight, run_plan, verify
from modules.project_controller import ProjectController
from modules.project_reviews import ReviewStore, claim_root, write_json
from modules.project_runtime import OwnershipUnconfirmed
from modules.project_workspace import ProjectDocument
from modules.run_charter import parse_charter
from testing.test_merge_orphans import POLICY


@pytest.fixture
def case(tmp_path, monkeypatch):
    project = ProjectDocument.create('NA999', 'H9999', tmp_path / 'project', [])
    claim_root(project)
    project.create_layout()
    values = dict(operating=dict(install_dir=str(tmp_path / 'install'), instance='ProbeOwned',
                                cache_dir=str(project.root / 'proc/tmp/cache'), reserve_gib=1),
                  science=dict(frame='utm:10N', min_component_size=37, custom_science='preserve'),
                  navigation={}, cameras={}, merge=dict(POLICY),
                  budget=dict(disk_delta_gb=1, cache_delta_gb=1))
    for name, value in values.items():
        project.set_settings(name, value)
        project.approve_settings(name, 'fixture operator')
    proof = project.root / 'metadata/alignment.json'
    for stage in ('inventory', 'navigation', 'georeference', 'preprocess', 'batch', 'align'):
        attempt = project.start_stage(stage, required_blocks=[])
        if stage == 'align':
            write_json(proof, {'verdict': 'ok', 'synthetic': True})
            project.record_output(stage, proof, attempt_id=attempt)
        project.complete_stage(stage, attempt_id=attempt)
    project.save()
    project.start_stage('merge', required_blocks=ProjectController.required_settings_blocks('merge'))
    project.save()
    root = project.root / 'proc/workflows/current'
    policy_path = project.root / 'metadata/merge_policies/raw.json'
    write_json(policy_path, POLICY)
    raw = dict(schema=1, campaign='TEST', dive='REFERENCE', locations=dict(results_root=str(root),
        originals=[], nav=[], protected=[]), ownership=dict(rs_instance='ProbeOwned',
        rs_cache_dir=values['operating']['cache_dir'], user_instances=[]), budget=values['budget'],
        science=dict(values['science'], orphan_policy=str(policy_path)), pipeline=dict(stages=['merge'], answers={}),
        signed_off=dict(by='fixture operator', date='2026-09-11', quote='approved settings'))
    charter_path = root / '_agent/raw.json'
    write_json(charter_path, raw)
    charter = parse_charter(raw, charter_path)
    context = dict(orphan_policy=dict(POLICY), orphan_policy_path=str(policy_path), workflow_root=str(root),
        selection_manifest=str(project.root / 'proc/selection/manifest.json'),
        occlusion_manifest=str(project.root / 'proc/masks/occlusion/approved.json'),
        occlusion_manifest_sha256='a' * 64, priors_file=str(project.root / 'metadata/priors/current.json'))
    controller = ProjectController()
    monkeypatch.setattr(verify, 'verify_workspace', lambda *a, **kw: {'verdict': 'ok'})
    monkeypatch.setattr(ReviewStore, 'selection', lambda self: [object()] * 5)
    yield SimpleNamespace(project=project, controller=controller, charter=charter,
        session=run_plan.session_from_charter(charter, stages=['merge']), context=context, proof=proof)
    controller._pool.shutdown(wait=True)


def call(case):
    return case.controller._prepare_merge_evidence(case.project, case.session, case.charter, case.context)


def test_probe_callback_records_current_project_attempt_and_rebuilds_only_policy(case, monkeypatch):
    commands = []
    def execute(records, agent_root, charter_path, **kw):
        assert kw['control'] is case.controller._control
        assert kw['observer'] == case.controller._observe
        commands.extend(records)
        return 0
    monkeypatch.setattr(rs, 'execute_commands', execute)
    evidence = case.project.root / 'metadata/validation/orphan_import.json'
    write_json(evidence, {'synthetic': True})
    def ensure(**kw):
        kw['assert_approved']()
        assert kw['environment']['RS_PROJECT_FILE'] == str(case.project.path)
        assert kw['max_original_cameras'] == 10
        manifest = {'path': str(case.project.root / 'proc/validation/orphan_import/a/probe.json'), 'sha256': 'b' * 64}
        assert kw['record_executor'](manifest) == 0
        return evidence
    monkeypatch.setattr(orphan_import_evidence, 'ensure_orphan_import_evidence', ensure)
    session, charter = call(case)
    assert len(commands) == 1
    record = commands[0]
    attempt = case.project.to_dict()['stages']['merge']['attempts'][-1]['id']
    assert record['project_id'] == case.project.project_id and record['project_attempt_id'] == attempt
    assert record['stage'] == 'merge' and record['needs_realityscan']
    assert record['argv'][3] == 'modules.orphan_import_probe'
    assert record['env']['RS_ORPHAN_EVIDENCE_CHILD'] == '1'
    assert record['env']['RS_EVENT_FILE'].endswith('runtime.jsonl')
    saved_plan = json.loads(next(case.project.root.glob('metadata/plans/*.json')).read_text())
    assert saved_plan['project_attempt_id'] == attempt
    assert '/_agent/' in saved_plan['run_state']
    assert saved_plan['purpose'] == 'orphan_import_readback'
    expected = copy.deepcopy(case.charter.raw)
    expected['science']['orphan_policy'] = charter.raw['science']['orphan_policy']
    assert charter.raw == expected
    assert session.min_component_size == 37
    assert json.loads(Path(session.orphan_policy).read_text()) == dict(POLICY, cli_probe_evidence=str(evidence))


def test_no_offered_orphans_preserves_raw_policy_and_ordinary_merge(case, monkeypatch):
    monkeypatch.setattr(orphan_import_evidence, 'ensure_orphan_import_evidence', lambda **kw: None)
    monkeypatch.setattr(rs, 'execute_commands', lambda *a, **kw: pytest.fail('Unexpected native work'))
    session, charter = call(case)
    assert session is case.session and charter is case.charter
    assert 'cli_probe_evidence' not in json.loads(Path(session.orphan_policy).read_text())


@pytest.mark.parametrize('fault', ['changed_output', 'missing_output', 'empty_output_proof', 'invalidated_alignment',
                                    'revoked_approval', 'changed_settings', 'workspace_invalid'])
def test_actual_saved_approvals_and_current_alignment_proof_are_required(case, monkeypatch, fault):
    if fault == 'changed_output':
        case.proof.write_text('changed')
    elif fault == 'missing_output':
        case.proof.unlink()
    elif fault == 'workspace_invalid':
        monkeypatch.setattr(verify, 'verify_workspace', lambda *a, **kw: {'verdict': 'incomplete'})
    else:
        data = json.loads(case.project.path.read_text())
        if fault == 'empty_output_proof':
            data['outputs'] = []
        elif fault == 'invalidated_alignment':
            data['stages']['align']['state'] = 'invalidated'
            for output in data['outputs']:
                output['valid'] = False
        elif fault == 'revoked_approval':
            data['settings']['merge']['approval'] = None
        else:
            data['settings']['merge']['values']['horizontal_margin_m'] += 1
        case.project.path.write_text(json.dumps(data))
    monkeypatch.setattr(orphan_import_evidence, 'ensure_orphan_import_evidence', lambda **kw: pytest.fail('Unapproved probe reached'))
    with pytest.raises(ValueError):
        call(case)
    assert not list(case.project.root.glob('metadata/plans/*.json'))


def test_approval_revoked_during_proof_stops_merge_handoff(case, monkeypatch):
    def ensure(**kw):
        kw['assert_approved']()
        data = json.loads(case.project.path.read_text())
        data['settings']['merge']['approval'] = None
        case.project.path.write_text(json.dumps(data))
        return None
    monkeypatch.setattr(orphan_import_evidence, 'ensure_orphan_import_evidence', ensure)
    with pytest.raises(ValueError, match='approval changed'):
        call(case)


def test_unconfirmed_owned_probe_propagates_actual_executor_record(case, monkeypatch):
    error = OwnershipUnconfirmed('retain this exact attempt', record={'real_runtime': True})
    monkeypatch.setattr(rs, 'execute_commands', lambda *a, **kw: (_ for _ in ()).throw(error))
    def ensure(**kw):
        return kw['record_executor']({'path': str(case.project.root / 'proc/validation/a/probe.json'), 'sha256': 'c' * 64})
    monkeypatch.setattr(orphan_import_evidence, 'ensure_orphan_import_evidence', ensure)
    with pytest.raises(OwnershipUnconfirmed) as exc:
        call(case)
    assert exc.value is error
    assert case.project.to_dict()['stages']['merge']['state'] == 'running'


def test_execute_stage_preflights_before_and_after_proof_then_plans(case, monkeypatch):
    from modules import deployment_preflight
    events = []
    monkeypatch.setattr(case.controller, 'ensure_cache', lambda p: None)
    monkeypatch.setattr(deployment_preflight, 'require_deployment', lambda **kw: {})
    monkeypatch.setattr(case.controller, '_prepare_session', lambda *a: (case.session, case.charter, case.context))
    def ready(*a):
        events.append('preflight')
        return dict(verdict='ready', blocking=[], missing=[])
    monkeypatch.setattr(preflight, 'preflight_charter', ready)
    def ensure(**kw):
        events.append('proof')
        kw['assert_approved']()
        return None
    monkeypatch.setattr(orphan_import_evidence, 'ensure_orphan_import_evidence', ensure)
    def build(*a, **kw):
        events.append('build')
        return {'warnings': [], 'commands': [{'stage': 'merge', 'argv': ['unused'], 'env': {}}]}
    monkeypatch.setattr(run_plan, 'build_plan', build)
    def execute(*a, **kw):
        events.append('execute')
        return 0
    monkeypatch.setattr(rs, 'execute_commands', execute)
    assert case.controller._execute_stage(case.project, 'merge')['verdict'] == 'ok'
    assert events == ['preflight', 'proof', 'preflight', 'build', 'execute']


def test_initial_failed_preflight_cannot_start_proof(case, monkeypatch):
    from modules import deployment_preflight
    monkeypatch.setattr(case.controller, 'ensure_cache', lambda p: None)
    monkeypatch.setattr(deployment_preflight, 'require_deployment', lambda **kw: {})
    monkeypatch.setattr(case.controller, '_prepare_session', lambda *a: (case.session, case.charter, case.context))
    monkeypatch.setattr(preflight, 'preflight_charter', lambda *a: dict(verdict='blocked', blocking=['not ready'], missing=[]))
    monkeypatch.setattr(orphan_import_evidence, 'ensure_orphan_import_evidence', lambda **kw: pytest.fail('Proof before preflight'))
    with pytest.raises(ValueError, match='Preflight requires'):
        case.controller._execute_stage(case.project, 'merge')
