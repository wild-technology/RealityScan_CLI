"""Automatic orchestration with synthetic native reports; never launch RealityScan."""
import copy
import csv
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest

import merge_zones as merge
from modules import orphan_import_evidence as automatic
from testing import rs_merge_orphan_probe as probe
from testing.test_merge_native_probe import planned, fake_recorder
from testing.test_merge_orphans import component
from modules.project_runtime import ExecutionControl, OwnershipUnconfirmed


def arguments(args, **extra):
    def execute(manifest):
        result = probe.record(manifest['path'], manifest['sha256'])
        return 0 if result['status'] == 'passed' else 2
    return dict(project_root=args['project_root'], components_root=args['components_root'],
                selection_manifest=args['selection_manifest'], policy_path=args['policy'],
                policy_sha256=probe.file_hash(args['policy']), install_dir=args['install_dir'],
                instance=args['instance'], reserve_gib=args['reserve_gib'],
                max_original_cameras=100, assert_approved=lambda: None, record_executor=execute, **extra)


def target(args):
    return Path(args['project_root']) / 'metadata/validation/orphan_import.json'


def add_component(plan, name, ids):
    comp = component(Path(plan['project_root']) / 'proc', name, ids)
    path = Path(comp['rsalign'])
    registration = path.parent / 'identity' / (path.stem + '.csv')
    with registration.open('w', newline='') as stream:
        stream.write(f'#cameras {len(ids)}\n')
        csv.writer(stream).writerows([[plan['images'][n]['path'], 0, 0, 0] for n in ids])
    Path(str(path) + '.manifest.json').write_text(json.dumps(dict(comp, schema=1)))
    return comp


def test_automatic_records_verifies_publishes_and_reuses(planned, monkeypatch):
    plan, args = planned
    calls = fake_recorder(monkeypatch)
    events = []
    kwargs = arguments(args, progress=events.append)
    result = automatic.ensure_orphan_import_evidence(**kwargs)
    assert result == target(args)
    assert len(calls) == 2
    assert not any(command == '-align' for _, commands in calls for command in commands)
    evidence = json.loads(result.read_text())
    recording = Path(evidence['recording_manifest']['path'])
    assert recording.is_relative_to(Path(args['project_root']) / 'proc/validation/orphan_import')
    recorded = json.loads(recording.read_text())
    assert recorded['controls'] == ['inside.jpg', 'between.jpg', 'remote.jpg']
    assert 'remote.jpg' not in recorded['offered']
    assert merge.validate_orphan_probe_evidence(result, args['project_root'])['status'] == 'passed'
    assert automatic.ensure_orphan_import_evidence(**kwargs) == result
    assert len(calls) == 2 and events[-1]['phase'] == 'reused'


def test_global_membership_removes_elsewhere_registered_control(planned, monkeypatch):
    plan, args = planned
    add_component(plan, 'c2', ['inside.jpg', 'a0.jpg', 'a1.jpg'])
    with pytest.raises(ValueError, match='inside, a corridor'):
        probe.build_plan(**args)
    census = probe.component_census(args['project_root'], args['components_root'])
    ctx = merge.load_orphan_context(None, None, [])
    _, audit = automatic.select_probe_pair(census, ctx, max_original_cameras=100)
    assert 'inside.jpg' not in audit['global_orphans']
    assert 'inside.jpg' in audit['globally_registered']
    assert all('inside.jpg' not in item['spatial_reasons'] for item in audit['rejected_pairs'])


def test_no_qualifying_pair_reports_reasons_without_launch(planned):
    plan, args = planned
    add_component(plan, 'c2', ['inside.jpg', 'a0.jpg', 'a1.jpg'])
    with pytest.raises(automatic.EvidenceBlocked, match='no_qualifying_pair') as exc:
        automatic.ensure_orphan_import_evidence(**arguments(args))
    report = json.loads(Path(exc.value.report).read_text())
    assert report['rejected_pairs']
    assert 'remote.jpg' in report['global_orphans']
    assert not target(args).exists()


def test_pair_selection_order_is_stable_and_skips_unqualified_small_pairs(planned):
    plan, args = planned
    # A measured remote triangle sorts before the valid 4+4 pair but has no corridor.
    extra = add_component(plan, 'c2', ['remote.jpg', 'a0.jpg', 'a1.jpg'])
    census = probe.component_census(args['project_root'], args['components_root'])
    context = merge.load_orphan_context(None, None, [])
    # Keep a second remote negative control available.
    context['images']['remote2.jpg'] = context['images']['remote.jpg']
    context['navigation']['remote2.jpg'] = copy.deepcopy(context['navigation']['remote.jpg'])
    paths, audit = automatic.select_probe_pair(census, context, max_original_cameras=100)
    again = automatic.select_probe_pair(census, context, max_original_cameras=100)
    assert again == (paths, audit)
    assert paths is not None
    # Pair identity comes from sorted full census, not caller-supplied pair order.
    assert extra['rsalign'] in census['paths']


@pytest.mark.parametrize('feature', ['missing', 'global'])
def test_missing_real_feature_readback_blocks_publication(planned, monkeypatch, feature):
    _, args = planned
    calls = fake_recorder(monkeypatch, feature=feature)
    with pytest.raises(automatic.EvidenceBlocked, match='native_proof_incomplete') as exc:
        automatic.ensure_orphan_import_evidence(**arguments(args))
    assert exc.value.details['unavailable'] == ['feature_source']
    assert [s for s, _ in calls] == ['before', 'prepared']
    assert not target(args).exists()


def test_failed_final_replay_does_not_publish_even_if_record_returns_pass(planned, monkeypatch):
    _, args = planned
    monkeypatch.setattr(probe, 'record', lambda *a: {'status': 'passed'})
    monkeypatch.setattr(probe, 'verify', lambda *a, **kw: {'status': 'failed'})
    with pytest.raises(automatic.EvidenceBlocked, match='verification_failed'):
        automatic.ensure_orphan_import_evidence(**arguments(args))
    assert not target(args).exists()


def test_recorder_does_not_write_ready_pointer_before_verification(planned, monkeypatch):
    plan, _ = planned
    manifest = probe.prepare(plan)
    fake_recorder(monkeypatch)
    monkeypatch.setattr(probe, 'verify', lambda *a, **kw: {'status': 'failed'})
    assert probe.record(manifest['path'], manifest['sha256'])['status'] == 'failed'
    assert not Path(plan['root'], 'orphan_import.json').exists()


@pytest.mark.parametrize('precondition', ['approval', 'policy', 'alignment', 'cancel'])
def test_preconditions_refuse_before_attempt_writes(planned, precondition):
    plan, args = planned
    kwargs = arguments(args)
    if precondition == 'approval':
        def refuse():
            raise ValueError('approval required')
        kwargs['assert_approved'] = refuse
    elif precondition == 'policy':
        kwargs['policy_sha256'] = '0' * 64
    elif precondition == 'alignment':
        Path(plan['components'][0]['rsalign']).unlink()
    else:
        kwargs['cancelled'] = lambda: True
    with pytest.raises((ValueError, InterruptedError)):
        automatic.ensure_orphan_import_evidence(**kwargs)
    assert not Path(args['project_root'], 'proc/validation').exists()
    assert not target(args).exists()


def test_cancel_after_record_retains_artifacts_without_publication(planned, monkeypatch):
    _, args = planned
    stop = threading.Event()
    original = probe.record
    fake_recorder(monkeypatch)
    def record(*a):
        result = original(*a)
        stop.set()
        return result
    monkeypatch.setattr(probe, 'record', record)
    with pytest.raises(InterruptedError):
        automatic.ensure_orphan_import_evidence(**arguments(args, cancelled=stop.is_set))
    assert not target(args).exists()
    assert list(Path(args['project_root']).glob('proc/validation/orphan_import/*/import_capture.json'))


def test_added_component_invalidates_recorded_census(planned, monkeypatch):
    plan, args = planned
    fake_recorder(monkeypatch)
    path = automatic.ensure_orphan_import_evidence(**arguments(args))
    evidence = json.loads(path.read_text())
    add_component(plan, 'c2', ['inside.jpg', 'a0.jpg', 'a1.jpg'])
    with pytest.raises(ValueError, match='census changed'):
        probe.verify(**dict(manifest=evidence['recording_manifest']['path'],
                            expected_sha256=evidence['recording_manifest']['sha256']))


def test_hash_cancellation_is_observed_inside_large_file(planned, monkeypatch):
    _, args = planned
    large = Path(args['project_root']) / 'large.bin'
    large.write_bytes(b'x' * (20 * 1024**2))
    calls = []
    def cancelled():
        calls.append(True)
        return len(calls) >= 4
    with probe.execution_context(cancelled=cancelled):
        with pytest.raises(InterruptedError):
            probe.bound(large)
    assert len(calls) == 4


def test_native_stage_cancellation_uses_canonical_run_control(planned, monkeypatch):
    plan, _ = planned
    manifest = probe.prepare(plan)
    prepared = probe.load_plan(manifest['path'], manifest['sha256'])
    stop = threading.Event()
    controls = []
    class FakeCLI:
        def __init__(self, *a, **kw):
            pass
        def run_batch_script(self, script, args, logs, *, control):
            controls.append(control)
            stop.set()
            assert control._requested.wait(2), 'cancel bridge failed to request owned abort'
            return SimpleNamespace(success=False, ownership_retained=False)
    monkeypatch.setattr(probe, 'RealityScanCLI', FakeCLI)
    with probe.execution_context(cancelled=stop.is_set):
        with pytest.raises(InterruptedError):
            probe.run_stage(prepared, 'before', ['-newScene'])
    assert controls[0].mode == 'abort_current'


@pytest.mark.parametrize('global_empty', [False, True])
def test_no_offered_orphans_returns_not_required_without_executor(planned, monkeypatch, global_empty):
    _, args = planned
    original_loader = merge.load_orphan_context
    def context(*a, **kw):
        ctx = original_loader(*a, **kw)
        if global_empty:
            registered = set().union(*map(set, probe.component_census(args['project_root'], args['components_root'])['members']))
            ctx['images'] = {n: row for n, row in ctx['images'].items() if n in registered}
        else:
            for name in ('inside.jpg', 'between.jpg'):
                ctx['navigation'][name] = copy.deepcopy(ctx['navigation']['remote.jpg'])
        return ctx
    monkeypatch.setattr(merge, 'load_orphan_context', context)
    kwargs = arguments(args)
    kwargs['record_executor'] = None
    events = []
    kwargs['progress'] = events.append
    assert automatic.ensure_orphan_import_evidence(**kwargs) is None
    assert not target(args).exists()
    assert events[-1]['phase'] == 'not_required'
    audit = json.loads(Path(events[-1]['report']).read_text())
    assert audit['status'] == 'not_required' and not audit['any_offered']


def test_empty_pair_attempt_does_not_require_proof_or_write_inputs(tmp_path):
    from testing.test_merge_orphans import context
    comps, ctx = context(tmp_path, ready=False)
    ctx['navigation']['within.jpg'] = copy.deepcopy(ctx['navigation']['remote.jpg'])
    evidence, inputs = merge.prepare_orphan_attempt(ctx, comps, tmp_path / 'attempt')
    assert inputs is None and not evidence['refused']
    assert evidence['cli_status'] == 'not_required'
    assert not (tmp_path / 'attempt/images').exists()
    assert set(ctx['images']) == {'within.jpg', 'remote.jpg'}


def test_empty_global_attempt_does_not_need_navigation_footprint(tmp_path):
    from testing.test_merge_orphans import context
    comps, ctx = context(tmp_path, ready=False)
    ctx['registered'].update(ctx['images'])
    ctx['navigation'] = {}
    evidence, inputs = merge.prepare_orphan_attempt(ctx, comps, tmp_path / 'attempt')
    assert not evidence['refused'] and inputs is None


def test_budget_is_explicit_not_fixed_test_ceiling(planned, monkeypatch):
    _, args = planned
    fake_recorder(monkeypatch)
    evidence = json.loads(automatic.ensure_orphan_import_evidence(**arguments(args)).read_text())
    plan = json.loads(Path(evidence['recording_manifest']['path']).read_text())
    assert plan['max_original_cameras'] == 100 and plan['import_only']


def test_approved_budget_refuses_offered_pair_without_launch(planned):
    _, args = planned
    kwargs = arguments(args)
    kwargs['max_original_cameras'] = 6
    with pytest.raises(automatic.EvidenceBlocked, match='no_qualifying_pair') as exc:
        automatic.ensure_orphan_import_evidence(**kwargs)
    audit = json.loads(Path(exc.value.report).read_text())
    assert audit['any_offered']
    assert audit['rejected_pairs'][0]['reason'] == 'approved_original_camera_budget_exceeded'


def test_controller_ownership_exception_propagates_unchanged(planned):
    _, args = planned
    record_holder = []
    exc = OwnershipUnconfirmed('retained', record={'actual': True})
    def execute(record):
        record_holder.append(record)
        raise exc
    kwargs = arguments(args)
    kwargs['record_executor'] = execute
    with pytest.raises(OwnershipUnconfirmed) as caught:
        automatic.ensure_orphan_import_evidence(**kwargs)
    assert caught.value is exc
    manifest = record_holder[0]
    assert set(manifest) == {'path', 'sha256'}
    assert probe.file_hash(manifest['path']) == manifest['sha256']
    assert not target(args).exists()


def test_execution_control_modes_and_upgrade_are_bridged(planned, monkeypatch):
    plan, _ = planned
    manifest = probe.prepare(plan)
    prepared = probe.load_plan(manifest['path'], manifest['sha256'])
    external = ExecutionControl()
    modes = []
    class FakeCLI:
        def __init__(self, *a, **kw):
            pass
        def run_batch_script(self, *a, control):
            assert control is not external
            for mode in ('after_step', 'abort_current'):
                external.request_cancel(mode)
                limit = time.monotonic() + 2
                while not (control.cancellation_requested and control.mode == mode) and time.monotonic() < limit:
                    time.sleep(.01)
                assert control.cancellation_requested and control.mode == mode
                modes.append(control.mode)
                assert control.reason == 'controller'
            return SimpleNamespace(success=False, ownership_retained=False)
    monkeypatch.setattr(probe, 'RealityScanCLI', FakeCLI)
    with probe.execution_context(control=external):
        with pytest.raises(InterruptedError):
            probe.run_stage(prepared, 'before', ['-newScene'])
    assert modes == ['after_step', 'abort_current']


def test_retained_native_ownership_wins_over_cancellation(planned, monkeypatch):
    plan, _ = planned
    manifest = probe.prepare(plan)
    prepared = probe.load_plan(manifest['path'], manifest['sha256'])
    external = ExecutionControl()
    class FakeCLI:
        def __init__(self, *a, **kw):
            pass
        def run_batch_script(self, *a, **kw):
            external.request_cancel('abort_current')
            return SimpleNamespace(success=False, ownership_retained=True, run_id='actual-native-run', log_path='native.log')
    monkeypatch.setattr(probe, 'RealityScanCLI', FakeCLI)
    with probe.execution_context(control=external):
        with pytest.raises(OwnershipUnconfirmed) as exc:
            probe.run_stage(prepared, 'before', ['-newScene'])
    assert exc.value.runtime_run_id == 'actual-native-run'
    assert exc.value.record['env']['RS_EVENT_FILE'].endswith('runtime.jsonl')
    assert Path(exc.value.runtime_record_path).is_file()


def test_controller_child_native_stages_share_attributed_runtime_channels(planned, monkeypatch):
    plan, _ = planned
    manifest = probe.prepare(plan)
    prepared = probe.load_plan(manifest['path'], manifest['sha256'])
    parent = 'a' * 32
    root = Path(plan['project_root']) / 'proc/tmp' / parent
    environment = dict(RS_RUN_ID=parent, RS_RUNTIME_ROOT=str(root), RS_CONTROL_FILE=str(root / 'control.json'),
                       RS_EVENT_FILE=str(root / 'runtime.jsonl'), RS_ERRORS_DIR=str(root / 'markers'),
                       RS_ORPHAN_EVIDENCE_CHILD='1')
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    class FakeCLI:
        def __init__(self, *a, **kw):
            pass
        def run_batch_script(self, *a, **kw):
            import os
            assert all(os.environ[k] == v for k, v in environment.items())
            return SimpleNamespace(success=True, ownership_retained=False)
    monkeypatch.setattr(probe, 'RealityScanCLI', FakeCLI)
    probe.run_stage(prepared, 'before', ['-newScene'])
    probe.run_stage(prepared, 'prepared', ['-newScene'])


def test_production_imports_without_testing_package():
    import subprocess
    import sys
    code = '''import sys, importlib.abc
class DenyTesting(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'testing' or fullname.startswith('testing.'):
            raise ImportError('testing package is not deployed')
sys.meta_path.insert(0, DenyTesting())
from modules import orphan_import_evidence, orphan_import_probe
assert orphan_import_probe.REPO.is_dir()
'''
    subprocess.run([sys.executable, '-B', '-c', code], cwd=probe.REPO, check=True, capture_output=True, timeout=30)


def test_explicit_environments_are_thread_local_and_never_mutate_process(planned, monkeypatch):
    import os
    from concurrent.futures import ThreadPoolExecutor
    _, args = planned
    original_loader = merge.load_orphan_context
    barrier = threading.Barrier(2)
    seen = []
    def loader(*a, **kw):
        env = kw['env']
        barrier.wait(timeout=5)
        seen.append((env['RS_PROJECT_FILE'], probe._ENVIRONMENT.get()['RS_PROJECT_FILE']))
        return original_loader(*a, **kw)
    monkeypatch.setattr(merge, 'load_orphan_context', loader)
    before = dict(os.environ)
    def plan(name):
        env = {'RS_PROJECT_FILE': name, 'RS_SELECTION_MANIFEST': args['selection_manifest']}
        with probe.execution_context(environment=env):
            result = probe.build_plan(**dict(args, run_name=name))
        return result['environment']
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(plan, ['first', 'second']))
    assert {tuple(row) for row in seen} == {('first', 'first'), ('second', 'second')}
    assert [r['RS_PROJECT_FILE'] for r in results] == ['first', 'second']
    assert dict(os.environ) == before and probe._ENVIRONMENT.get() is None


def test_helper_forwards_explicit_environment_without_global_changes(planned, monkeypatch):
    import os
    _, args = planned
    original_loader = merge.load_orphan_context
    env = {'RS_PROJECT_FILE': str(Path(args['project_root']) / 'active.rovscan')}
    seen = []
    def loader(*a, **kw):
        seen.append(kw['env'])
        return original_loader(*a, **kw)
    monkeypatch.setattr(merge, 'load_orphan_context', loader)
    before = dict(os.environ)
    fake_recorder(monkeypatch)
    assert automatic.ensure_orphan_import_evidence(**arguments(args, environment=env)).is_file()
    assert all(value == env for value in seen)
    assert dict(os.environ) == before


def test_native_failure_without_reports_has_structured_block_reason(planned):
    _, args = planned
    kwargs = arguments(args)
    kwargs['record_executor'] = lambda manifest: 1
    with pytest.raises(automatic.EvidenceBlocked, match='native_proof_unverifiable') as exc:
        automatic.ensure_orphan_import_evidence(**kwargs)
    assert exc.value.details['exit_code'] == 1
    assert not target(args).exists()


@pytest.mark.parametrize('baseline,prepared', [(False, False), (False, True), (True, True)])
def test_export_masks_only_for_stages_with_assigned_layers(planned, monkeypatch, baseline, prepared):
    plan, _ = planned
    plan['import_only'] = True
    if not prepared:
        plan['masks'] = {}
    if baseline:
        plan['masks'][plan['members'][0][0]] = plan['masks']['between.jpg']
    manifest = probe.prepare(plan)
    calls = fake_recorder(monkeypatch)
    assert probe.record(manifest['path'], manifest['sha256'])['status'] == 'passed'
    assert len(calls) == 2
    assert any(c.startswith('-exportMasks ') for c in calls[0][1]) is baseline
    assert any(c.startswith('-exportMasks ') for c in calls[1][1]) is prepared
    if baseline:
        identity = plan['members'][0][0]
        commands = calls[0][1]
        select = f'-selectImage "{plan["component_images"][identity]}"'
        assert commands[commands.index(select) + 1] == f'-setImagesLayer "{plan["masks"][identity]["path"]}" mask'


def test_zero_expected_masks_still_rejects_unexpected_export(tmp_path):
    directory = tmp_path / 'masks'
    directory.mkdir()
    (directory / 'surprise.png').write_bytes(b'unexpected')
    with pytest.raises(ValueError, match='Unknown'):
        probe.read_masks(directory, {'inputs': []}, {})
