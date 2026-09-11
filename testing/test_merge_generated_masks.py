"""Merge consumes the real post-batch approval API; all artifacts are offline."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import merge_zones as merge
from modules import project_occlusion
from modules.project_reviews import ReviewStore
from testing.test_project_occlusion import case, applied, approve
from testing.test_merge_orphans import POLICY, component


def bind(case, monkeypatch, decision):
    approve(case, decision)
    monkeypatch.setenv('RS_SELECTION_MANIFEST', str(case.selection))
    monkeypatch.setenv('RS_OCCLUSION_MANIFEST', str(case.project.resolve_path(decision['canonical_manifest'])))
    monkeypatch.setenv('RS_OCCLUSION_MANIFEST_SHA256', decision['canonical_sha256'])


def test_generated_canonical_masks_map_to_orphans_without_source_masks(case, monkeypatch):
    _, decision = applied(case)
    bind(case, monkeypatch, decision)
    selection = json.loads(case.selection.read_text())
    assert selection['masks'] == []
    readback = merge.load_project_occlusion(batch_root=str(case.batch))
    assert len(readback['masks']) == len(case.items)
    assert {m['sha256'] for m in readback['masks'].values()} == {m['mask']['sha256'] for m in decision['mappings']}
    assert all('/masters/' in Path(m['path']).as_posix() for m in readback['masks'].values())

    members = [[Path(i.path).name for i in case.items[:4]], [Path(i.path).name for i in case.items[4:8]]]
    comps = [component(case.project.root / 'proc', f'component_{i}', ids) for i, ids in enumerate(members)]
    policy = case.project.root / 'proc/policy.json'
    policy.write_text(json.dumps(POLICY))
    original = ReviewStore.require_approved
    def require(store, name):
        if name in ('quality', 'spatial'):
            return {'assessment_hash': selection[name + '_review_hash']}
        return original(store, name)
    monkeypatch.setattr(ReviewStore, 'require_approved', require)
    context = merge.load_orphan_context(case.selection, policy, comps, recording_probe=True)
    assert context['masks'] == readback['masks']
    assert context['fingerprint']['occlusion'] == readback

    # Exercise data staging independently of calibration/RS on two offered IDs.
    context.pop('calibration_profiles')
    offered = sorted(readback['masks'])[8:10]
    directory = case.project.root / 'proc/attempt'
    directory.mkdir()
    inputs = merge.stage_orphan_inputs(context, offered, directory)
    lines = Path(inputs['masks']).read_text().splitlines()
    assert len(lines) == 2
    assert {Path(line.split('|')[0]).name for line in lines} == set(offered)
    assert len(readback['masks']) == 24  # Excluded assignments stay globally available.


def test_approved_skip_is_mask_free_and_missing_binding_never_launches(case, monkeypatch):
    decision = project_occlusion.skip(case.project, project_occlusion.context(case.project), 'Reviewed skip', 'tester')
    bind(case, monkeypatch, decision)
    context = merge.load_project_occlusion()
    assert context['decision'] == 'skipped' and context['masks'] == {}
    monkeypatch.delenv('RS_OCCLUSION_MANIFEST_SHA256')
    with pytest.raises(ValueError, match='requires approved'):
        merge.run_merge_workflow(SimpleNamespace(run_batch_script=lambda *a: pytest.fail('Native launch reached')),
            'components', 'output', 'name', 'align', [], None, None, str(case.batch), 'logs', False, None)


def test_explicit_project_environment_ignores_other_controller_globals(case, monkeypatch):
    decision = project_occlusion.skip(case.project, project_occlusion.context(case.project), 'Reviewed skip', 'tester')
    approve(case, decision)
    env = dict(RS_SELECTION_MANIFEST=str(case.selection),
               RS_OCCLUSION_MANIFEST=str(case.project.resolve_path(decision['canonical_manifest'])),
               RS_OCCLUSION_MANIFEST_SHA256=decision['canonical_sha256'], RS_PROJECT_FILE=str(case.project.path))
    monkeypatch.setenv('RS_SELECTION_MANIFEST', 'another-project')
    monkeypatch.setenv('RS_PROJECT_FILE', 'another-project.rovscan')
    result = merge.load_project_occlusion(env=env, batch_root=str(case.batch))
    assert result['decision'] == 'skipped'


@pytest.mark.parametrize('change', ['hash', 'mask_pixels', 'batch_image', 'approval'])
def test_changed_occlusion_refuses_before_attempt_writes(case, monkeypatch, change):
    _, decision = applied(case)
    bind(case, monkeypatch, decision)
    binding = merge.load_project_occlusion()
    if change == 'hash':
        monkeypatch.setenv('RS_OCCLUSION_MANIFEST_SHA256', '0' * 64)
    elif change == 'mask_pixels':
        Path(next(iter(binding['masks'].values()))['path']).write_bytes(b'changed mask')
    elif change == 'batch_image':
        next(case.batch.rglob('frame000.png')).write_bytes(b'changed pixels')
    else:
        case.store.put('occlusion_review', {'decision': 'pending'})
    directory = case.project.root / 'proc/refused_attempt'
    with pytest.raises((ValueError, OSError)):
        merge.prepare_orphan_attempt({'occlusion': binding}, [], directory)
    assert not directory.exists()
