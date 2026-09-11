"""Offline native mask integration; real images/engine, fake approved selection."""
import json
import os
from dataclasses import replace
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

from PIL import Image
import pytest

from modules import project_occlusion as masks
from modules.image_batcher.batch_directory import validate_selection_manifest
from modules.project_reviews import ReviewStore, claim_root, digest, write_json
from modules.project_workspace import ProjectDocument
from modules.source_inventory import SourceInventory, SourceItem, approval_token, file_hash
from testing.test_temporal_occlusion import fixture_frames


def log(path, names):
    path.parent.mkdir(parents=True, exist_ok=True)
    header = ['Filename', 'X (East)', 'Y (North)', 'Alt'] + ['value'] * 10
    path.write_text(';'.join(header) + '\n' + ''.join(name + ';' + ';'.join(['1'] * 13) + '\n' for name in names))
    return path


@pytest.fixture
def case(tmp_path, monkeypatch, request):
    source, frames = fixture_frames(tmp_path)
    transparency = getattr(request, 'param', None)
    if transparency:
        mode, color, options = {
            'RGBA': ('RGBA', (40, 70, 90, 128), {}),
            'RGBA_opaque': ('RGBA', (40, 70, 90, 255), {}),
            'LA': ('LA', (70, 128), {}),
            'RGB_tRNS': ('RGB', (40, 70, 90), {'transparency': (40, 70, 90)}),
            'L_tRNS': ('L', 70, {'transparency': 70}),
            'P_tRNS': ('P', 0, {'transparency': 0}),
        }[transparency]
        with Image.new(mode, (192, 128), color) as image:
            image.save(frames[0].path, **options)
        frames[0] = replace(frames[0], sha256=file_hash(Path(frames[0].path)))
    project = ProjectDocument.create('NA999', 'H9999', tmp_path / 'project', sources=[source])
    claim_root(project)
    project.set_settings('operating', {'reserve_gib': 0})
    project.approve_settings('operating', 'tester')
    for stage in ('inventory', 'navigation', 'georeference', 'preprocess', 'batch'):
        attempt = project.start_stage(stage)
        project.complete_stage(stage, attempt_id=attempt)
    project.save()
    family = next(key for key in masks.camera_registry.FAMILY_CAMERA if 'lower' in key)
    camera = masks.camera_registry.FAMILY_CAMERA[family]
    items = SourceInventory([SourceItem(str(frame.path), 'acquisition/' + Path(frame.path).name, 'image',
                        Path(frame.path).stat().st_size, Path(frame.path).stat().st_mtime_ns,
                        camera=camera, family=family, timestamp_utc=frame.timestamp_utc,
                        sha256=frame.sha256, window_status='inside') for frame in frames],
                        source_root=source, fingerprint='a'*64, hashing_complete=True, verification_complete=True)
    monkeypatch.setattr(ReviewStore, 'selection', lambda self: items)
    selection_hash = approval_token(items)
    selected = project.root / 'proc' / 'selections' / selection_hash
    image_root = selected / 'images'
    for item in items:
        destination = image_root / camera / Path(item.path).name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(item.path, destination)
    flight = log(selected / 'navigation' / 'flight_log_4Q_UTM.txt', [Path(item.path).name for item in items])
    selection_path = selected / 'selection.json'
    selection = dict(schema=1, project_id=project.project_id, selection_hash=selection_hash,
        quality_review_hash='a' * 64, spatial_review_hash='b' * 64,
        images_root=str(image_root), flight_log=str(flight), flight_log_sha256=file_hash(flight), epsg=32604,
        masks=[], images=[dict(path=str(image_root / camera / Path(item.path).name), sha256=item.sha256) for item in items])
    write_json(selection_path, selection)
    workflow = project.root / 'proc' / 'workflows' / selection_hash
    batch = workflow / 'batched_images_by_zone'
    zone_logs = {}
    for name, members in (('zone_1', items[:18]), ('zone_2', items[6:])):
        zone = batch / name
        for item in members:
            destination = zone / camera / Path(item.path).name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item.path, destination)
        flight = log(zone / 'flight_log_4Q_UTM.txt', [Path(item.path).name for item in members])
        zone_logs[name] = dict(file=flight.name, sha256=file_hash(flight))
    marker = dict(status='complete', params={'batch_zone_layout': 'copy'}, zone_flight_logs=zone_logs,
                  selection=validate_selection_manifest(selection_path, image_root, selection['flight_log']))
    write_json(batch / 'batch_inputs.json', marker)
    store = ReviewStore(project)
    store.put('workflow', dict(selection_hash=selection_hash, root=workflow.relative_to(project.root).as_posix(),
                              selection_manifest=selection_path.relative_to(project.root).as_posix()))
    return SimpleNamespace(project=project, items=items, batch=batch, source=source, store=store,
                           selection=selection_path, marker=marker)


def generate(case):
    context = masks.context(case.project)
    payload = masks.generate(case.project, context)
    assert len(payload['groups']) == 1
    assert payload['groups'][0]['status'] == 'candidate_review_required'
    return context, payload


def applied(case):
    context, generated = generate(case)
    decision = masks.apply(case.project, context, generated, 'tester')
    return context, decision


def approve(case, payload):
    review = case.store.put('occlusion_review', payload)
    case.store.approve('occlusion_review', review['assessment_hash'], 'tester')


def test_census_and_generation_have_canonical_overlap_identity(case):
    original = {path: file_hash(path) for path in case.source.iterdir()}
    context, generated = generate(case)
    assert len(context['frames']) == 24 and len(context['copies']) == 36
    group = generated['groups'][0]
    assert group['image_count'] == 24 and group['sample_count'] == 24
    assert group['block_seconds'] == 900
    assert group['start_unix'] % group['block_seconds'] == 0
    assert 0 < group['excluded_fraction'] < .4 and group['previews']
    assert generated['parameter_schema'] == masks.parameter_schema()
    assert masks.context(case.project)['batch_fingerprint'] == context['batch_fingerprint']
    assert not list(case.batch.rglob('*.mask.png'))
    assert {path: file_hash(path) for path in case.source.iterdir()} == original


def test_apply_fullres_overlap_copies_and_validate(case):
    context, decision = applied(case)
    assert len(decision['mappings']) == 24 and len(decision['copies']) == 36
    assert decision['groups'][0]['status'] == 'candidate_review_required'
    current = masks.context(case.project)
    assert current['batch_fingerprint'] == context['batch_fingerprint']
    per_image = {}
    for row in decision['copies']:
        path = case.project.resolve_path(row['path'])
        assert path.name.endswith('.png.mask.png')
        with Image.open(path) as image:
            assert image.size == (192, 128) and image.mode == 'L'
            assert {value for count, value in image.getcolors(3)} == {0, 255}
        per_image.setdefault(row['image_id'], set()).add(row['sha256'])
    assert all(len(hashes) == 1 for hashes in per_image.values())
    assert masks.validate(case.project, context, decision)['canonical_sha256'] == decision['canonical_sha256']


def test_skip_receipts_survive_review_replacement_then_reapply(case):
    context, decision = applied(case)
    canonical = case.project.resolve_path(decision['canonical_manifest'])
    before = canonical.read_bytes()
    case.store.put('occlusion_review', {'decision': 'pending'})
    skipped = masks.skip(case.project, context, 'No masks this time', 'tester')
    assert not list(case.batch.rglob('*.mask.png'))
    assert canonical.read_bytes() == before
    assert masks.validate(case.project, context, skipped)['decision'] == 'skipped'
    _, second = applied(case)
    assert masks.validate(case.project, context, second)['decision'] == 'applied'


@pytest.mark.parametrize('decision_type', ['applied', 'skipped'])
def test_external_gate_reuses_current_approved_decision(case, decision_type):
    context = masks.context(case.project)
    decision = applied(case)[1] if decision_type == 'applied' else masks.skip(case.project, context, 'No exclusions', 'tester')
    approve(case, decision)
    result = masks.validate_external(case.project.resolve_path(decision['canonical_manifest']),
        decision['canonical_sha256'], case.selection, case.batch)
    assert result['decision'] == decision_type and result['project_root'] == str(case.project.root)
    with pytest.raises(ValueError, match='differs'):
        masks.validate_external(case.project.resolve_path(decision['canonical_manifest']), '0' * 64, case.selection)


@pytest.mark.parametrize('change', ['image', 'new_image', 'missing_image', 'zone_log', 'marker', 'new_zone'])
def test_rebatch_or_changed_inputs_never_reuse_proposal(case, change):
    context, generated = generate(case)
    image = next(case.batch.rglob('frame000.png'))
    if change == 'image':
        image.write_bytes(image.read_bytes() + b'changed')
    elif change == 'new_image':
        shutil.copyfile(image, image.with_name('unexpected.png'))
    elif change == 'missing_image':
        image.unlink()
    elif change == 'zone_log':
        next(case.batch.rglob('flight_log*.txt')).write_text('changed')
    elif change == 'marker':
        case.marker['params']['changed'] = True
        write_json(case.batch / 'batch_inputs.json', case.marker)
    else:
        (case.batch / 'zone_3').mkdir()
    with pytest.raises(ValueError):
        masks.apply(case.project, context, generated, 'tester')
    assert not list(case.batch.rglob('*.mask.png'))


def test_foreign_mask_not_overwritten_or_deleted(case):
    context, generated = generate(case)
    image = next(case.batch.rglob('frame000.png'))
    foreign = image.with_name(image.name + '.mask.png')
    foreign.write_bytes(b'foreign operator content')
    assert masks.context(case.project)['batch_fingerprint'] == context['batch_fingerprint']
    with pytest.raises(ValueError, match='Unowned'):
        masks.apply(case.project, context, generated, 'tester')
    with pytest.raises(ValueError, match='Unowned'):
        masks.skip(case.project, context, 'No masks', 'tester')
    assert foreign.read_bytes() == b'foreign operator content'


def test_cancelled_apply_rolls_back_owned_partial_copies(case):
    context, generated = generate(case)
    stop = []
    def progress(stage, done, total, path):
        if stage == 'copy':
            stop.append(True)
    with pytest.raises(InterruptedError):
        masks.apply(case.project, context, generated, 'tester', cancelled=lambda: bool(stop), progress=progress)
    assert not list(case.batch.rglob('*.mask.png'))
    assert masks.skip(case.project, context, 'Cancelled review', 'tester')['decision'] == 'skipped'


@pytest.mark.parametrize('method', ['generate', 'apply', 'skip'])
def test_cancelled_before_mutation(case, method):
    context = masks.context(case.project)
    before = set(case.project.root.rglob('*'))
    args = {'generate': (), 'apply': ({}, 'tester'), 'skip': ('No masks', 'tester')}[method]
    with pytest.raises(InterruptedError):
        getattr(masks, method)(case.project, context, *args, cancelled=lambda: True)
    assert set(case.project.root.rglob('*')) == before


@pytest.mark.parametrize('target', ['canonical', 'master', 'copy'])
def test_tampered_applied_evidence_fails_closed(case, target):
    context, decision = applied(case)
    relative = {'canonical': decision['canonical_manifest'], 'master': decision['mappings'][0]['mask']['path'],
                'copy': decision['copies'][0]['path']}[target]
    path = case.project.resolve_path(relative)
    path.write_bytes(path.read_bytes() + b'changed')
    with pytest.raises(ValueError):
        masks.validate(case.project, context, decision)


def test_replaced_owned_copy_preserved(case):
    context, decision = applied(case)
    path = case.project.resolve_path(decision['copies'][0]['path'])
    content = path.read_bytes()
    alias = path.with_name('different-file')
    alias.write_bytes(content)
    os.replace(alias, path)
    with pytest.raises(ValueError, match='replaced'):
        masks.skip(case.project, context, 'Skip', 'tester')
    assert path.read_bytes() == content


def test_storage_refusal_precedes_artifact_writes(case, monkeypatch):
    context = masks.context(case.project)
    def refuse(*args, **kwargs):
        raise ValueError('fixture disk budget exceeded')
    monkeypatch.setattr(masks, 'require_start_space', refuse)
    with pytest.raises(ValueError, match='budget'):
        masks.generate(case.project, context)
    assert not (case.project.root / masks.ARTIFACT_ROOT).exists()


def test_acquisition_domain_changes_extent_without_using_overlap_paths(case):
    first = masks.context(case.project)
    ids = {row['sha256']: row['frame_extent'] for row in first['frames']}
    case.items[0].relative_path = 'different_acquisition/' + Path(case.items[0].path).name
    path = next(case.batch.rglob('frame000.png'))
    _, _, extent = masks._extent(path, case.items[0])
    assert extent != ids[case.items[0].sha256]
    assert 'cannot prove equal physical framing' in first['extent_limit']


@pytest.mark.parametrize('condition', ['pool', 'incomplete', 'active_align'])
def test_unsupported_or_active_stage_refused(case, condition):
    if condition == 'active_align':
        context = masks.context(case.project)
        case.project.start_stage('align')
        with pytest.raises(ValueError, match='running'):
            masks.generate(case.project, context)
        return
    if condition == 'pool':
        case.marker['params']['batch_zone_layout'] = 'pool'
    else:
        case.marker['status'] = 'in_progress'
    write_json(case.batch / 'batch_inputs.json', case.marker)
    with pytest.raises(ValueError):
        masks.context(case.project)


def test_mutable_alignment_artifacts_do_not_invalidate_masks(case):
    context, decision = applied(case)
    image = next(case.batch.rglob('frame000.png'))
    image.with_suffix('.xmp').write_text('solved pose written by alignment')
    (image.parent.parent / 'alignment.log').write_text('runtime progress')
    (image.parent.parent / 'checkpoint.json').write_text('{}')
    assert masks.validate(case.project, context, decision)['decision'] == 'applied'


def test_apply_replaces_owned_masks_without_skip_and_preserves_ui(case):
    context, first = applied(case)
    old_master = case.project.resolve_path(first['mappings'][0]['mask']['path'])
    before = old_master.read_bytes()
    proposal = masks.generate(case.project, context)
    case.store.put('occlusion_review', proposal)
    second = masks.apply(case.project, context, proposal, 'another reviewer')
    assert old_master.read_bytes() == before
    assert second['canonical_manifest'] != first['canonical_manifest']
    assert second['groups'] == proposal['groups'] and second['parameters'] == proposal['parameters']
    assert masks.validate(case.project, context, second)['decision'] == 'applied'


@pytest.mark.parametrize('method', ['apply', 'skip'])
def test_tampered_old_copy_prevents_all_deletions(case, method):
    context, old = applied(case)
    proposal = masks.generate(case.project, context)
    last = case.project.resolve_path(old['copies'][-1]['path'])
    last.write_bytes(b'operator changed this last copy')
    before = {p: p.read_bytes() for p in case.batch.rglob('*.mask.png')}
    with pytest.raises(ValueError):
        if method == 'apply':
            masks.apply(case.project, context, proposal, 'tester')
        else:
            masks.skip(case.project, context, 'Skip', 'tester')
    assert {p: p.read_bytes() for p in case.batch.rglob('*.mask.png')} == before


def test_durable_artifacts_and_schema_defaults(case):
    _, decision = applied(case)
    assert decision['canonical_manifest'].startswith('proc/masks/occlusion/')
    assert all(row['mask']['path'].startswith('proc/masks/occlusion/') for row in decision['mappings'])
    defaults = {row['key']: row['default'] for row in masks.parameter_schema()}
    masks.engine.TemporalMaskConfig(**defaults).validate()
    assert all(row['min'] <= row['default'] <= row['max'] for row in masks.parameter_schema())


def test_validate_decodes_master_once_for_all_canonical_images(case, monkeypatch):
    context, decision = applied(case)
    master = case.project.resolve_path(decision['mappings'][0]['mask']['path'])
    original, opened = masks.Image.open, []
    def track(path, *args, **kwargs):
        if Path(path) == master:
            opened.append(path)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(masks.Image, 'open', track)
    masks.validate(case.project, context, decision)
    assert len(opened) == 1


@pytest.mark.parametrize('location', ['root', 'folder', 'zone_folder', 'orphan'])
def test_unknown_mask_layers_fail_closed(case, location):
    if location == 'root':
        path = case.batch / 'frame000.png.mask.png'
    elif location == 'folder':
        path = case.batch / '_mask' / 'frame000.png'
    elif location == 'zone_folder':
        path = case.batch / 'zone_1' / '.mask' / 'frame000.png'
    else:
        path = case.batch / 'zone_1' / 'unknown.png.mask.png'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'foreign')
    with pytest.raises(ValueError, match='mask'):
        masks.context(case.project)
    assert path.read_bytes() == b'foreign'


def test_apply_copy_receipt_failure_rolls_back_without_source_changes(case, monkeypatch):
    context, proposal = generate(case)
    original = masks.write_json
    def fail_receipt(path, value):
        if path.name == 'copies.json' and value['copies']:
            raise OSError('fixture receipt disk failure')
        return original(path, value)
    monkeypatch.setattr(masks, 'write_json', fail_receipt)
    with pytest.raises(OSError, match='receipt'):
        masks.apply(case.project, context, proposal, 'tester')
    assert not list(case.batch.rglob('*.mask.png'))


def test_copy_fsync_failure_cleans_only_own_partial_target(case, monkeypatch):
    image = next(case.batch.rglob('frame000.png'))
    path = image.with_name(image.name + '.mask.png')
    def fail(fd):
        raise OSError('fixture fsync failure')
    folder = masks._new_folder(case.project)
    journal = masks._CopyJournal(case.project, folder, masks._relative(case.project, case.batch))
    try:
        monkeypatch.setattr(masks.os, 'fsync', fail)
        with pytest.raises(OSError, match='fsync'):
            masks._copy_mask(case.project, path, b'mask bytes', 'x' * 64, journal=journal, image_id='image')
    finally:
        journal.close()
    assert not path.exists()
    assert not list(folder.glob('*.partial'))


def test_mapping_binds_canonical_selected_image(case):
    _, decision = applied(case)
    for row in decision['mappings']:
        assert row['image']['path'].startswith('proc/selections/')
        assert file_hash(case.project.resolve_path(row['image']['path'])) == row['image']['sha256']


def test_external_save_as_uses_explicit_document_without_choosing_newest(case, monkeypatch):
    context = masks.context(case.project)
    decision = masks.skip(case.project, context, 'No exclusions', 'tester')
    approve(case, decision)
    second = case.project.save(case.project.root / 'saved-as.rovscan')
    manifest = case.project.resolve_path(decision['canonical_manifest'])
    monkeypatch.delenv('RS_PROJECT_FILE', raising=False)
    with pytest.raises(ValueError, match='explicit'):
        masks.validate_external(manifest, decision['canonical_sha256'], case.selection)
    assert masks.validate_external(manifest, decision['canonical_sha256'], case.selection,
                                   project_file=second)['decision'] == 'skipped'
    monkeypatch.setenv('RS_PROJECT_FILE', str(second))
    assert masks.validate_external(manifest, decision['canonical_sha256'], case.selection)['decision'] == 'skipped'


def test_context_propagates_cancellation_to_selection_validator(case, monkeypatch):
    from modules.image_batcher import batch_directory
    def validator(*args, cancelled=None):
        assert callable(cancelled)
        raise InterruptedError('fixture selection cancellation')
    monkeypatch.setattr(batch_directory, 'validate_selection_manifest', validator)
    with pytest.raises(InterruptedError, match='selection cancellation'):
        masks.context(case.project, cancelled=lambda: False)


def test_modified_preview_payload_cannot_approve_different_canonical_evidence(case):
    context, proposal = generate(case)
    proposal['groups'][0]['previews'][0]['overlay_path'] = 'different-preview.png'
    with pytest.raises(ValueError, match='immutable manifest'):
        masks.apply(case.project, context, proposal, 'tester')
    assert not list(case.batch.rglob('*.mask.png'))


@pytest.mark.parametrize('case', ['RGBA', 'RGBA_opaque', 'LA', 'RGB_tRNS', 'L_tRNS', 'P_tRNS'], indirect=True)
def test_embedded_alpha_cannot_be_approved_by_skip_or_validation(case):
    # Selection and batch hashes already bind these exact synthetic inputs, so
    # rejection must be the geometry policy, not a stale-input shortcut.
    before = {path: file_hash(path) for path in case.project.root.rglob('*') if path.is_file()}
    source_before = {path: file_hash(path) for path in case.source.iterdir()}
    calls = [lambda: masks.context(case.project),
             lambda: masks.skip(case.project, {}, 'Use no masks', 'tester'),
             lambda: masks.validate(case.project, payload={'decision': 'skipped'})]
    for call in calls:
        with pytest.raises(ValueError, match='Embedded alpha/transparency.*Supply opaque geometry inputs'):
            call()
    assert {path: file_hash(path) for path in case.project.root.rglob('*') if path.is_file()} == before
    assert {path: file_hash(path) for path in case.source.iterdir()} == source_before
    assert not (case.project.root / masks.ARTIFACT_ROOT).exists()


def test_process_local_priors_do_not_change_mask_census_or_reopen(case, monkeypatch, tmp_path):
    context = masks.context(case.project)
    decision = masks.skip(case.project, context, 'No masks', 'tester')
    approve(case, decision)
    item = case.items[0]
    camera = masks.camera_registry.CAMERAS[item.camera]
    # Simulate another worker's prior/calibration snapshot without changing the
    # physical camera key, persisted batch, or approved project settings.
    monkeypatch.setitem(masks.camera_registry.CAMERAS, item.camera,
                        replace(camera, calibration_group='999', focal_length_35mm=42.0))
    priors_path = tmp_path / 'worker-priors.json'
    write_json(priors_path, dict(schema_version=1, orientation_weight=2,
        families={item.family: dict(fwd=1.5, pitch=35, p_acc=17)},
        defaults=dict(position_accuracy_m=dict(x=8), orientation_accuracy_deg=dict(yaw=12))))
    snapshot = masks.camera_registry.load_project_priors(str(priors_path))
    monkeypatch.setattr(masks.camera_registry, '_PROJECT_PRIORS', snapshot)
    assert masks.camera_registry.mount_defaults()[item.family]['p_acc'] == 17
    assert masks.context(case.project)['batch_fingerprint'] == context['batch_fingerprint']
    assert masks.validate(case.project, context, decision)['decision'] == 'skipped'
    assert masks.validate_external(case.project.resolve_path(decision['canonical_manifest']),
                                   decision['canonical_sha256'], case.selection,
                                   project_file=case.project.path)['decision'] == 'skipped'


@pytest.mark.parametrize('change', ['crop', 'shape', 'camera'])
def test_extent_still_binds_observed_frame_and_physical_camera(case, change):
    item = case.items[0]
    image_path = next(case.batch.rglob('frame000.png'))
    before = masks._extent(image_path, item)
    if change == 'camera':
        family = next(key for key, camera in masks.camera_registry.FAMILY_CAMERA.items() if camera != item.camera)
        item = replace(item, family=family, camera=masks.camera_registry.FAMILY_CAMERA[family])
    else:
        with Image.open(image_path) as opened:
            image = opened.copy()
        if change == 'crop':
            exif = Image.Exif()
            exif[50720] = (160, 128)
            image.save(image_path, exif=exif)
        else:
            image.resize((160, 128)).save(image_path)
    assert masks._extent(image_path, item) != before


# These child processes really exit without Python cleanup. All paths are the
# fixture's private project; no controller, application or shared runtime locks.
CRASH_COPY = r'''
import hashlib, os, sys
from pathlib import Path
from modules import project_occlusion as masks
from modules.project_workspace import ProjectDocument
project = ProjectDocument.load(Path(sys.argv[1]))
target, batch, stop = Path(sys.argv[2]), sys.argv[3], sys.argv[4]
folder = masks._new_folder(project)
journal = masks._CopyJournal(project, folder, batch)
append = journal.append
promote = masks._promote_exclusive
def crash_append(entry):
    if stop == 'unproven' and entry['event'] == 'prepared':
        return
    append(entry)
    if entry['event'] == stop:
        os._exit(73)
def crash_promote(source, destination):
    promote(source, destination)
    if stop in ('promoted', 'unproven'):
        os._exit(73)
journal.append = crash_append
masks._promote_exclusive = crash_promote
content = b'complete fixture mask bytes'
masks._copy_mask(project, target, content, hashlib.sha256(content).hexdigest(),
                 journal=journal, image_id='fixture-image')
os._exit(74)
'''


def crash_copy(case, stop):
    image = next(case.batch.rglob('frame000.png'))
    target = image.with_name(image.name + '.mask.png')
    batch = masks._relative(case.project, case.batch)
    result = subprocess.run([sys.executable, '-c', CRASH_COPY, str(case.project.path),
                             str(target), batch, stop], capture_output=True, text=True, timeout=30)
    assert result.returncode == 73, result.stdout + result.stderr
    return target


@pytest.mark.parametrize('stop', ['prepared', 'promoted', 'published'])
def test_process_death_recovery_requires_durable_identity(case, stop):
    context = masks.context(case.project)
    source_before = {p: file_hash(p) for p in case.source.iterdir()}
    target = crash_copy(case, stop)
    journal = next((case.project.root / masks.ARTIFACT_ROOT).glob('*/copies.jsonl'))
    journal_before = journal.read_bytes()
    assert target.exists() == (stop != 'prepared')
    if target.exists():
        relative = masks._relative(case.project, target)
        owned = masks._owned_copies(case.project, [relative])
        assert owned[relative]['identity'] == masks._identity(target)
    # Recovery is an explicit Apply/Skip, never an approval inferred from a log.
    with pytest.raises(ValueError):
        masks.validate(case.project)
    skipped = masks.skip(case.project, context, 'Recover interrupted publication', 'tester')
    assert skipped['decision'] == 'skipped' and not target.exists()
    assert journal.read_bytes() == journal_before
    assert {p: file_hash(p) for p in case.source.iterdir()} == source_before


def test_reapply_after_process_death_keeps_canonical_overlap(case):
    context, proposal = generate(case)
    crash_copy(case, 'promoted')
    decision = masks.apply(case.project, context, proposal, 'tester')
    assert len(decision['copies']) == 36
    assert masks.validate(case.project, context, decision)['decision'] == 'applied'


@pytest.mark.parametrize('change', ['same_hash_replacement', 'changed_content', 'no_identity'])
def test_recovery_never_claims_foreign_or_modified_target(case, change):
    context = masks.context(case.project)
    target = crash_copy(case, 'unproven' if change == 'no_identity' else 'promoted')
    if change == 'same_hash_replacement':
        other = target.with_name('foreign.partial')
        other.write_bytes(target.read_bytes())
        os.replace(other, target)
    elif change == 'changed_content':
        target.write_bytes(b'operator changed this file')
    before = target.read_bytes()
    with pytest.raises(ValueError, match='Unowned|content changed'):
        masks.skip(case.project, context, 'Never delete foreign content', 'tester')
    assert target.read_bytes() == before


@pytest.mark.parametrize('tail', [b'{"entry":', b'{"entry": null}\n'])
def test_recovery_torn_tail_vs_complete_corrupt_record(case, tail):
    context = masks.context(case.project)
    target = crash_copy(case, 'promoted')
    journal = next((case.project.root / masks.ARTIFACT_ROOT).glob('*/copies.jsonl'))
    with journal.open('ab') as stream:
        stream.write(tail)
    if tail.endswith(b'\n'):
        with pytest.raises(ValueError, match='journal'):
            masks.skip(case.project, context, 'Recover', 'tester')
        assert target.exists()
    else:
        assert masks.skip(case.project, context, 'Recover', 'tester')['decision'] == 'skipped'
        assert not target.exists()


@pytest.mark.parametrize('history', ['compact', 'journal'])
def test_changed_historical_mask_cannot_block_current_apply_validate_skip(case, history):
    old = case.project.root / 'proc/workflows/obsolete/batched_images_by_zone/zone_1/lower/old.png.mask.png'
    old.parent.mkdir(parents=True)
    folder = masks._new_folder(case.project)
    old_batch = masks._relative(case.project, old.parents[2])
    if history == 'compact':
        old.write_bytes(b'old mask')
        record = dict(masks._record(case.project, old), identity=masks._identity(old))
        write_json(folder / 'copies.json', dict(version=masks.VERSION, project_id=case.project.project_id, copies=[record]))
    else:
        journal = masks._CopyJournal(case.project, folder, old_batch)
        try:
            content = b'old mask'
            masks._copy_mask(case.project, old, content, masks.hashlib.sha256(content).hexdigest(),
                             journal=journal, image_id='old-image')
        finally:
            journal.close()
    old.write_bytes(b'operator modified historical mask')
    history_before = {p: p.read_bytes() for p in folder.iterdir()}
    context, decision = applied(case)
    assert masks.validate(case.project, context, decision)['decision'] == 'applied'
    assert masks.skip(case.project, context, 'No masks now', 'tester')['decision'] == 'skipped'
    assert old.read_bytes() == b'operator modified historical mask'
    assert {p: p.read_bytes() for p in folder.iterdir()} == history_before


def test_receipt_is_compacted_once_and_journal_records_are_linear(case, monkeypatch):
    original, snapshots = masks.write_json, []
    def track(path, value):
        if path.name == 'copies.json':
            snapshots.append(len(value['copies']))
        return original(path, value)
    monkeypatch.setattr(masks, 'write_json', track)
    _, decision = applied(case)
    count = len(decision['copies'])
    assert snapshots == [count]
    journal = case.project.resolve_path(decision['canonical_manifest']).parent / 'copies.jsonl'
    entries = [json.loads(line)['entry'] for line in journal.read_text().splitlines()]
    assert len(entries) == 1 + 2 * count
    assert all('copies' not in entry for entry in entries)
    assert [entry['event'] for entry in entries[1:]] == ['prepared', 'published'] * count


def test_exclusive_promotion_cannot_replace_racing_same_hash_foreign_file(case, monkeypatch):
    context, proposal = generate(case)
    original, foreign = masks._promote_exclusive, []
    def race(source, target):
        target.write_bytes(source.read_bytes())
        foreign.append((target, masks._identity(target), target.read_bytes()))
        original(source, target)
    monkeypatch.setattr(masks, '_promote_exclusive', race)
    with pytest.raises(FileExistsError):
        masks.apply(case.project, context, proposal, 'tester')
    assert len(foreign) == 1
    path, identity, content = foreign[0]
    assert masks._identity(path) == identity and path.read_bytes() == content
    with pytest.raises(ValueError, match='Unowned'):
        masks.skip(case.project, context, 'Preserve racing foreign file', 'tester')


def test_apply_budgets_one_master_per_group_then_actual_copy_bytes(case, monkeypatch):
    context, proposal = generate(case)
    requested = []
    monkeypatch.setattr(masks, '_reserve', lambda project, size: requested.append(size))
    decision = masks.apply(case.project, context, proposal, 'tester')
    frame = context['frames'][0]
    assert requested[0] == frame['width'] * frame['height'] * 2 + 65536 + proposal['groups'][0]['assessment']['bytes'] * 3
    mapping = {row['image_id']: row for row in decision['mappings']}
    copy_bytes, metadata_bytes = masks._copy_budget(context, mapping, proposal, 'tester')
    assert copy_bytes == sum(row['bytes'] for row in decision['copies'])
    assert requested[1] == requested[2] == copy_bytes + metadata_bytes
    assert requested[-1] == metadata_bytes
    folder = case.project.resolve_path(decision['canonical_manifest']).parent
    written_metadata = sum(p.stat().st_size for p in folder.iterdir() if p.is_file())
    assert metadata_bytes >= written_metadata


def test_shared_master_large_copy_budget_uses_encoded_size():
    # 100,000 camera images may share a tiny binary PNG. No pixel-sized copy or
    # per-member master allocations should enter the publication budget.
    count = 100_000
    live = dict(copies=[dict(path=f'proc/workflows/current/zone_{i}/image.jpg', image_id='shared') for i in range(count)])
    mapping = dict(shared=dict(mask=dict(path='proc/masks/master.png', sha256='a' * 64, bytes=512),
                               width=1975, height=1975))
    body = dict(groups=[], parameters={}, parameter_schema=[])
    data, metadata = masks._copy_budget(live, mapping, body, 'tester')
    assert data == count * 512
    assert data + metadata < 2 * masks.GIB


def test_encoded_copy_budget_refusal_preserves_old_masks(case, monkeypatch):
    context, previous = applied(case)
    proposal = masks.generate(case.project, context)
    before = {p: p.read_bytes() for p in case.batch.rglob('*.mask.png')}
    calls = []
    def reserve(project, size):
        calls.append(size)
        if len(calls) == 2:
            raise ValueError('fixture actual encoded-copy budget refusal')
    monkeypatch.setattr(masks, '_reserve', reserve)
    with pytest.raises(ValueError, match='encoded-copy budget'):
        masks.apply(case.project, context, proposal, 'tester')
    assert {p: p.read_bytes() for p in case.batch.rglob('*.mask.png')} == before
    assert masks.validate(case.project, context, previous)['decision'] == 'applied'


def test_reserve_rechecked_after_copying_rolls_back_partial_transaction(case, monkeypatch):
    context, proposal = generate(case)
    calls = []
    def reserve(project, size):
        calls.append(size)
        if len(calls) == 4:
            raise ValueError('fixture reserve consumed by another writer')
    monkeypatch.setattr(masks, '_reserve', reserve)
    with pytest.raises(ValueError, match='another writer'):
        masks.apply(case.project, context, proposal, 'tester')
    assert len(calls) == 4 and not list(case.batch.rglob('*.mask.png'))


def test_promotion_identity_ignores_rename_times_but_never_file_id():
    before = SimpleNamespace(st_dev=12, st_ino=123, st_ctime_ns=100, st_birthtime_ns=100)
    renamed = SimpleNamespace(st_dev=12, st_ino=123, st_ctime_ns=200, st_birthtime_ns=50)
    foreign = SimpleNamespace(st_dev=12, st_ino=124, st_ctime_ns=100, st_birthtime_ns=100)
    assert masks._stable_identity(before) == masks._stable_identity(renamed)
    assert masks._stable_identity(before) != masks._stable_identity(foreign)
    with pytest.raises(ValueError, match='file identity'):
        masks._stable_identity(SimpleNamespace(st_dev=12, st_ino=0))
