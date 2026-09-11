"""Project opt-in gate before batching; legacy callers remain unaffected."""
import csv
import hashlib
import json
import logging
import os
from pathlib import Path

import pytest

from module_base.parameter import Parameter
from modules.image_batcher.batch_directory import BatchDirectory, validate_selection_manifest


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def selected(tmp_path):
    project = tmp_path / 'project'
    root = project / 'proc/selections/current/images'
    camera = root / 'camera'
    camera.mkdir(parents=True)
    (project / '.rovscan-owner.json').write_text(json.dumps({'project_id': 'project-id'}))
    images = []
    for name in ('a.jpg', 'b.jpg'):
        path = camera / name
        path.write_bytes(name.encode())
        images.append({'path': str(path), 'sha256': digest(path)})
    mask = camera / 'a.jpg.mask.png'
    mask.write_bytes(b'mask bytes')
    log = root.parent / 'navigation/flight_log_10N_UTM.txt'
    log.parent.mkdir()
    header = ['filename', 'X (East)', 'Y (North)', 'Alt', 'X Accuracy', 'Y Accuracy', 'Alt Accuracy',
              'Yaw', 'Pitch', 'Roll', 'Yaw Accuracy', 'Pitch Accuracy', 'Roll Accuracy', 'FocalLength']
    with log.open('w', newline='') as stream:
        writer = csv.writer(stream, delimiter=';')
        writer.writerow(header)
        writer.writerows([[Path(item['path']).name, *(['1'] * 13)] for item in images])
    manifest = dict(schema=1, project_id='project-id', selection_hash='a' * 64,
        quality_review_hash='b' * 64, spatial_review_hash='c' * 64, images_root=str(root),
        flight_log=str(log), flight_log_sha256=digest(log), epsg=32610, images=images,
        masks=[{'path': str(mask), 'sha256': digest(mask)}])
    path = root.parent / 'selection.json'
    path.write_text(json.dumps(manifest))
    return root, log, path, manifest


def module(tmp_path, root, log):
    mod = BatchDirectory(logging.getLogger(__name__))
    mod.params = mod.get_parameters()
    mod.params['output_dir'] = Parameter('Output', 'o', 'output_dir', str, str(tmp_path / 'workflow'), 'output')
    mod.params['batch_input_image_dir'].set_value(str(root))
    mod.params['batch_flight_log_path'].set_value(str(log))
    mod.params['batch_target_images_per_zone'].set_value(100)
    mod.params['batch_min_zone_size'].set_value(50)
    mod.params['batch_max_zone_size'].set_value(200)
    return mod


def test_exact_set_and_order_independence(selected):
    root, log, path, manifest = selected
    first = validate_selection_manifest(path, root, log)
    manifest['images'].reverse()
    path.write_text(json.dumps(manifest, indent=2))
    assert first == validate_selection_manifest(path, root, log)


@pytest.mark.parametrize('fault', ['extra', 'missing', 'pixels', 'mask', 'extra_mask', 'missing_mask_entry',
                                  'log', 'owner', 'frame', 'empty', 'duplicate_path', 'duplicate_content'])
def test_mismatches_refused(selected, fault):
    root, log, path, manifest = selected
    a, b = (Path(item['path']) for item in manifest['images'])
    if fault == 'extra':
        (root / 'excluded.jpg').write_bytes(b'excluded')
    elif fault == 'missing':
        a.unlink()
    elif fault == 'pixels':
        stat = a.stat()
        a.write_bytes(b'wrong')  # same byte count; restore mtime as well
        os.utime(a, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    elif fault == 'mask':
        Path(manifest['masks'][0]['path']).write_bytes(b'changed mask')
    elif fault == 'extra_mask':
        b.with_name('b.jpg.mask.png').write_bytes(b'unreviewed mask')
    elif fault == 'missing_mask_entry':
        manifest['masks'] = []
    elif fault == 'log':
        log.write_text(log.read_text().replace('a.jpg', 'excluded.jpg'))
        manifest['flight_log_sha256'] = digest(log)
    elif fault == 'owner':
        manifest['project_id'] = 'wrong-project'
    elif fault == 'frame':
        manifest['epsg'] = 32611
    elif fault == 'empty':
        manifest['images'] = []
    elif fault == 'duplicate_path':
        manifest['images'].append(manifest['images'][0])
    elif fault == 'duplicate_content':
        b.write_bytes(a.read_bytes())
        manifest['images'][1]['sha256'] = digest(b)
    path.write_text(json.dumps(manifest))
    with pytest.raises((ValueError, FileNotFoundError)):
        validate_selection_manifest(path, root, log)


def test_actual_input_and_log_cannot_be_substituted(selected, tmp_path):
    root, log, path, _ = selected
    wrong = tmp_path / 'preprocessed_images'
    wrong.mkdir()
    with pytest.raises(ValueError, match='Actual batch input'):
        validate_selection_manifest(path, wrong, log)
    other_log = root / 'other_10N_UTM.txt'
    other_log.write_bytes(log.read_bytes())
    with pytest.raises(ValueError, match='Actual batch flight log'):
        validate_selection_manifest(path, root, other_log)


@pytest.mark.parametrize('redirect', ['navigation', 'images'])
def test_manifest_cannot_borrow_another_selection_tree(selected, redirect):
    root, log, path, manifest = selected
    other = path.parent.parent / 'other-selection'
    other.mkdir()
    if redirect == 'navigation':
        borrowed = other / log.name
        borrowed.write_bytes(log.read_bytes())
        manifest['flight_log'] = str(borrowed)
        log = borrowed
    else:
        # Reject even if actual input and manifest agree on the other tree.
        manifest['images_root'] = str(other)
        root = other
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='Actual batch'):
        validate_selection_manifest(path, root, log)


def test_legacy_navigation_inside_selected_images_still_accepted(selected):
    root, log, path, manifest = selected
    inline = root / log.name
    inline.write_bytes(log.read_bytes())
    manifest['flight_log'] = str(inline)
    path.write_text(json.dumps(manifest))
    assert validate_selection_manifest(path, root, inline)['selection_hash'] == manifest['selection_hash']


def test_real_materialize_selection_handoff(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from PIL import Image
    from modules.project_staging import materialize_selection
    from modules.project_reviews import ReviewStore
    from modules.source_inventory import scan_source, hash_identities, apply_dive_window
    source = tmp_path / 'source'
    source.mkdir()
    names = ['camlower_20250524T010000Z.jpg', 'camlower_20250524T010001Z.jpg']
    for name, color in zip(names, ('red', 'blue')):
        Image.new('RGB', (16, 16), color).save(source / name)
    Image.new('L', (16, 16), 255).save(source / (names[0] + '.mask.png'))
    inventory = scan_source(source)
    hash_identities(inventory)
    apply_dive_window(inventory, '2025-05-24T00:00:00Z', '2025-05-24T02:00:00Z')
    project = SimpleNamespace(root=tmp_path / 'project', project_id='materialized')
    project.resolve_path = lambda value: project.root / value
    project.root.mkdir()
    (project.root / '.rovscan-owner.json').write_text(json.dumps({'project_id': project.project_id}))
    monkeypatch.setattr(ReviewStore, 'selection', lambda self: inventory)
    monkeypatch.setattr(ReviewStore, 'require_approved', lambda *args: {'assessment_hash': 'b' * 64})
    log = tmp_path / 'flight_log_10N_UTM.txt'
    with log.open('w', newline='') as stream:
        writer = csv.writer(stream, delimiter=';')
        writer.writerow(['filename', 'X (East)', 'Y (North)', 'Alt'] + [str(i) for i in range(10)])
        writer.writerows([[name, *(['1'] * 13)] for name in names])
    manifest, path = materialize_selection(project, log, expected_epsg=32610, reserve_bytes=0)
    assert Path(manifest['flight_log']).parent == path.parent / 'navigation'
    assert Path(manifest['images_root']) == path.parent / 'images'
    assert manifest['masks']
    assert validate_selection_manifest(path, manifest['images_root'], manifest['flight_log'])['project_id'] == project.project_id


def test_gate_before_validation_writes_and_direct_run(selected, tmp_path, monkeypatch):
    root, log, path, _ = selected
    monkeypatch.setenv('RS_SELECTION_MANIFEST', str(path))
    (root / 'extra.jpg').write_bytes(b'not approved')
    mod = module(tmp_path, root, log)
    monkeypatch.setattr('builtins.input', lambda *a: pytest.fail('prompt reached before selection gate'))
    monkeypatch.setattr(mod, '_BatchDirectory__read_flight_log_gdf', lambda *a: pytest.fail('zoning reached before gate'))
    assert mod.validate_parameters()[0] is False
    assert mod.run()['Success'] is False
    assert not (tmp_path / 'workflow').exists()


def test_sticky_binding_and_fingerprint(selected, tmp_path, monkeypatch):
    root, log, path, manifest = selected
    monkeypatch.setenv('RS_SELECTION_MANIFEST', str(path))
    mod = module(tmp_path, root, log)
    fp = mod._input_fingerprint(str(log))
    assert fp['selection']['selection_hash'] == manifest['selection_hash']
    monkeypatch.delenv('RS_SELECTION_MANIFEST')
    with pytest.raises(ValueError, match='requires RS_SELECTION_MANIFEST'):
        mod._require_selection_manifest()
    monkeypatch.setenv('RS_SELECTION_MANIFEST', str(path))
    manifest['quality_review_hash'] = 'd' * 64
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='changed during batching'):
        mod._require_selection_manifest()


def test_valid_gate_and_legacy_compatibility(selected, tmp_path, monkeypatch):
    root, log, path, _ = selected
    monkeypatch.delenv('RS_SELECTION_MANIFEST', raising=False)
    legacy = module(tmp_path, root, log)
    assert legacy._require_selection_manifest() is None
    assert 'selection' not in legacy._input_fingerprint(str(log))
    monkeypatch.setenv('RS_SELECTION_MANIFEST', str(path))
    project = module(tmp_path, root, log)
    assert project.validate_parameters() == (True, None)
    assert (tmp_path / 'workflow/batched_images_by_zone').is_dir()


def test_changed_approval_during_overwrite_prompt_preserves_old_outputs(selected, tmp_path, monkeypatch):
    root, log, path, manifest = selected
    monkeypatch.setenv('RS_SELECTION_MANIFEST', str(path))
    mod = module(tmp_path, root, log)
    output = tmp_path / 'workflow/batched_images_by_zone'
    output.mkdir(parents=True)
    valuable = output / 'prior.txt'
    valuable.write_text('preserve')
    def prompt(*args):
        manifest['spatial_review_hash'] = 'd' * 64
        path.write_text(json.dumps(manifest))
        return 'y'
    monkeypatch.setattr('builtins.input', prompt)
    assert mod.validate_parameters()[0] is False
    assert valuable.read_text() == 'preserve'


def test_cancelled_before_validation_reads_nothing(selected, monkeypatch):
    root, log, path, _ = selected
    monkeypatch.setattr(Path, 'read_text', lambda *a, **kw: pytest.fail('Cancelled gate read a file'))
    with pytest.raises(InterruptedError, match='cancelled'):
        validate_selection_manifest(path, root, log, cancelled=lambda: True)


def test_cancellation_interrupts_large_image_hash_and_stops_remaining_files(selected, monkeypatch):
    from modules import source_inventory
    root, log, path, manifest = selected
    first, second = [Path(row['path']) for row in manifest['images']]
    first.write_bytes(b'a' * (20 * 1024 * 1024))
    manifest['images'][0]['sha256'] = digest(first)
    path.write_text(json.dumps(manifest))
    active, visited, checks = [None], [], [0]
    original = source_inventory.file_hash
    def hashing(file, *, cancelled=None):
        active[0] = Path(file)
        visited.append(Path(file))
        return original(file, cancelled=cancelled)
    def cancelled():
        if active[0] == first:
            checks[0] += 1
        return checks[0] >= 3  # Stop after the first chunk, inside file_hash.
    monkeypatch.setattr(source_inventory, 'file_hash', hashing)
    with pytest.raises(InterruptedError):
        validate_selection_manifest(path, root, log, cancelled=cancelled)
    assert first in visited and second not in visited and checks[0] == 3
    assert first.stat().st_size == 20 * 1024 * 1024
