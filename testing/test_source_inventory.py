from pathlib import Path
import os
import json

import pytest
from PIL import Image

from modules.source_inventory import (
    scan_source, hash_identities, apply_dive_window, verify_images, stage_inventory,
    approval_token, summarize_inventory, assert_source_unchanged, source_fingerprint,
    SourceInventory, SourceItem, copy_verified, reconcile_image_identities,
)


def image(path, color="white", size=(12, 8)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


def test_selected_variants_reconcile_without_rehash_and_preserve_other_errors(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    name = 'camupper_20250524T010000Z.jpg'
    image(source / 'original' / name, 'white')
    image(source / 'processed' / name, 'black')
    items = scan_source(source)
    hash_identities(items)
    retained, excluded = items
    retained.exception += '; independent decode finding'
    excluded.included = False
    from modules import source_inventory as module
    monkeypatch.setattr(module, 'file_hash', lambda *a, **k: pytest.fail('Selection must not rehash sources'))
    reconcile_image_identities(items)
    assert retained.exception == 'independent decode finding'
    assert excluded.exception == ''
    assert summarize_inventory(items)['cameras']['starboard']['conflicting_names'] == 1
    excluded.included = True
    reconcile_image_identities(items)
    assert all('different image content' in item.exception for item in items)
    assert 'independent decode finding' in retained.exception


def test_identity_reconciliation_rejects_missing_hash_before_changing_records(tmp_path):
    source = tmp_path / 'source'
    image(source / 'a' / 'camupper_20250524T010000Z.jpg')
    image(source / 'b' / 'camupper_20250524T010000Z.jpg')
    items = scan_source(source)
    hash_identities(items)
    items[-1].sha256 = ''
    before = [vars(item).copy() for item in items]
    with pytest.raises(ValueError, match='hashes are required'):
        reconcile_image_identities(items)
    assert [vars(item) for item in items] == before


def test_source_mismatch_reports_actual_expected_observed_and_root(tmp_path, monkeypatch):
    from modules import source_inventory as inventory
    source = tmp_path / 'source'
    image(source / 'camlower_20250524T010000Z.jpg')
    items = scan_source(source)
    expected = items.source_fingerprint
    (source / 'arrived.txt').write_text('new delivery')
    observed = source_fingerprint(source)
    assert observed != expected
    original = inventory.source_fingerprint
    calls = []

    def counted(root, **kwargs):
        calls.append(str(root))
        return original(root, **kwargs)
    monkeypatch.setattr(inventory, 'source_fingerprint', counted)
    with pytest.raises(ValueError, match='Source tree changed') as caught:
        assert_source_unchanged(items)
    message = str(caught.value)
    assert f'source_root={items.source_root!r}' in message
    assert f'expected={expected}' in message
    assert f'observed={observed}' in message
    assert calls == [items.source_root]  # No retry or silently accepted new snapshot.
    assert items.source_fingerprint == expected


def census_item(path, family, camera, *, sha256='a' * 64, **kwargs):
    return SourceItem(path, path, 'image', 1, 1, family=family, camera=camera,
                      sha256=sha256, **kwargs)


def test_family_census_preserves_mounts_and_all_camera_count_definitions():
    from copy import deepcopy
    photos = [
        census_item('a/upper.jpg', 'legacy_camupper', 'starboard', window_status='in_window'),
        census_item('b/upper.jpg', 'legacy_camupper', 'starboard', window_status='outside_window', included=False),
        census_item('c/upper.jpg', 'legacy_camupper', 'starboard', sha256='b' * 64, window_status='invalid_timestamp'),
        census_item('wca.jpg', 'wca_starboard', 'starboard'),
        census_item('mid.jpg', 'legacy_cammid', 'port'),
        census_item('lower.jpg', 'legacy_camlower', 'cinema'),
        census_item('zeuss.jpg', 'zeuss', 'zeuss'),
    ]
    items = photos + [
        SourceItem('upper.jpg.mask.png', 'upper.jpg.mask.png', 'mask', 1, 1,
                   family='legacy_camupper', camera='starboard', mask_for=photos[0].path),
        SourceItem('orphan.mask.png', 'orphan.mask.png', 'mask', 1, 1,
                   family='legacy_camupper', camera='starboard'),
    ]
    before = deepcopy(items)
    matches = {'unmatched': [{'path': 'wca.jpg', 'camera': 'starboard'}]}
    report = summarize_inventory(items, navigation_matches=matches)
    families = report['families']
    assert set(families) == {i.family for i in items}
    row = families['legacy_camupper']
    assert row == dict(family='legacy_camupper', camera='starboard', total=3,
        in_window=1, outside_window=1, invalid_timestamp=1, unassessed_window=0,
        included=2, unique=2, unique_content_hashes=2, identical_duplicates=1,
        conflicting_names=1, sidecar_identity_collisions=0, masks=2, unmatched_masks=1, unmatched=0)
    assert families['wca_starboard']['total'] == 1
    assert families['wca_starboard']['unmatched'] == 1
    assert report['cameras']['starboard']['total'] == 4
    assert report['cameras']['starboard']['unmatched'] == 1
    assert set(report['cameras']['starboard']) == set(row) - {'family', 'camera'}
    assert report == summarize_inventory(list(reversed(items)), navigation_matches=matches)
    assert items == before


def test_family_census_keeps_unhashed_counts_unknown_independently():
    items = [census_item('upper.jpg', 'legacy_camupper', 'starboard'),
             census_item('wca.jpg', 'wca_starboard', 'starboard', sha256='')]
    report = summarize_inventory(items)
    assert report['families']['legacy_camupper']['unique'] == 1
    for key in ('unique', 'unique_content_hashes', 'identical_duplicates', 'conflicting_names'):
        assert report['families']['wca_starboard'][key] is None
        assert report['cameras']['starboard'][key] is None
    assert report['families']['legacy_camupper']['unmatched'] is None


def test_family_census_uses_exact_keys_and_reports_mixed_camera_assignment():
    items = [census_item('unknown.jpg', '', ''),
             census_item('a/photo.jpg', 'CustomMount', 'port'),
             census_item('b/photo.jpg', 'CustomMount', 'cinema'),
             census_item('other.jpg', 'custommount', 'port')]
    report = summarize_inventory(items, navigation_matches={'unmatched': [
        {'path': 'unknown.jpg', 'camera': ''}]})
    assert set(report['families']) == {'', 'CustomMount', 'custommount'}
    assert report['families']['']['family'] == ''
    assert report['families']['']['camera'] == 'unknown'
    assert report['families']['']['unmatched'] == 1
    mixed = report['families']['CustomMount']
    assert mixed['camera'] is None and mixed['camera_conflict'] is True
    assert mixed['cameras'] == ['cinema', 'port']
    assert mixed['unique'] == 2 and mixed['identical_duplicates'] == 0


def test_family_census_reports_cross_family_xmp_collisions_for_each_mount():
    items = [census_item('a/photo.jpg', 'legacy_camlower', 'cinema'),
             census_item('b/photo.png', 'wca_cinema', 'cinema')]
    report = summarize_inventory(items)
    assert report['cameras']['cinema']['sidecar_identity_collisions'] == 1
    assert all(row['sidecar_identity_collisions'] == 1 for row in report['families'].values())
    items[1].included = False
    assert all(row['sidecar_identity_collisions'] == 0
               for row in summarize_inventory(items)['families'].values())


def test_family_census_includes_mask_only_families_and_ignores_map_sidecars():
    items = [SourceItem('orphan.png', 'orphan.png', 'mask', 1, 1,
                        family='legacy_cammid', camera='port'),
             SourceItem('map.tif', 'map.tif', 'map', 1, 1),
             SourceItem('old.xmp', 'old.xmp', 'sidecar', 1, 1)]
    report = summarize_inventory(items)
    assert set(report['families']) == {'legacy_cammid'}
    assert report['families']['legacy_cammid']['total'] == 0
    assert report['families']['legacy_cammid']['masks'] == 1
    assert report['families']['legacy_cammid']['unmatched_masks'] == 1
    assert report['maps'] == 1
    assert summarize_inventory([])['families'] == {}


@pytest.mark.parametrize('second_name', ['camlower_20250524T010000Z.png',
                                        'camlower_20250524T010000Z.jpeg',
                                        'CAMLOWER_20250524T010000Z.PNG'])
def test_cross_extension_xmp_identity_blocks_before_copy(tmp_path, second_name):
    source = tmp_path / 'source'
    image(source / 'images/zone1/camlower_20250524T010000Z.jpg')
    image(source / 'images/zone2' / second_name, 'black')
    items = scan_source(source)
    # Explicitly use the same physical camera even when its filename is uppercase.
    for photo in items:
        photo.camera = 'cinema'
        photo.exception = ''
    summary = summarize_inventory(items)
    assert summary['cameras']['cinema']['sidecar_identity_collisions'] == 1
    collision = summary['sidecar_identity_collisions'][0]
    assert collision['sidecar_name'] == 'camlower_20250524t010000z.xmp'
    assert len(collision['paths']) == 2
    assert summarize_inventory(list(reversed(items)))['sidecar_identity_collisions'] == [collision]
    hash_identities(items)
    apply_dive_window(items, '2025-05-24T00:00:00Z', '2025-05-24T02:00:00Z')
    with pytest.raises(ValueError, match='Sidecar identity collision'):
        stage_inventory(items, tmp_path / 'project', reserve_bytes=0, approved_token=approval_token(items))
    assert not (tmp_path / 'project').exists()
    assert all(photo.included and not photo.duplicate_of for photo in items)


def test_equal_content_different_extensions_still_require_explicit_exclusion(tmp_path):
    source = tmp_path / 'source'
    first = image(source / 'images/camlower_20250524T010000Z.jpg')
    second = first.with_suffix('.jpeg')
    second.write_bytes(first.read_bytes())
    items = scan_source(source)
    hash_identities(items)
    apply_dive_window(items, '2025-05-24T00:00:00Z', '2025-05-24T02:00:00Z')
    token = approval_token(items)
    assert len(summarize_inventory(items)['sidecar_identity_collisions']) == 1
    with pytest.raises(ValueError, match='Sidecar identity collision'):
        stage_inventory(items, tmp_path / 'project', reserve_bytes=0, approved_token=token)
    next(photo for photo in items if photo.path == str(second)).included = False
    assert approval_token(items) != token
    assert summarize_inventory(items)['sidecar_identity_collisions'] == []
    with pytest.raises(ValueError, match='explicitly confirmed'):
        stage_inventory(items, tmp_path / 'project', reserve_bytes=0, approved_token=token)
    result = stage_inventory(items, tmp_path / 'project', reserve_bytes=0, approved_token=approval_token(items))
    assert [p.name for p in Path(result['images_root']).rglob('*') if p.is_file()] == [first.name]
    assert (tmp_path / 'project/raw/imagery/images' / second.name).read_bytes() == second.read_bytes()


def test_same_stem_in_distinct_camera_folders_does_not_collide(tmp_path):
    source = tmp_path / 'source'
    image(source / 'images/camlower_20250524T010000Z.jpg')
    image(source / 'images/camlower_20250524T010000Z.png')
    items = scan_source(source)
    items[1].camera = 'port'  # Explicit project camera override.
    hash_identities(items)
    apply_dive_window(items, '2025-05-24T00:00:00Z', '2025-05-24T02:00:00Z')
    assert summarize_inventory(items)['sidecar_identity_collisions'] == []
    result = stage_inventory(items, tmp_path / 'project', reserve_bytes=0, approved_token=approval_token(items))
    assert len([p for p in Path(result['images_root']).rglob('*') if p.is_file()]) == 2


def test_same_basename_zone_copies_keep_existing_duplicate_policy(tmp_path):
    source = tmp_path / 'source'
    name = 'camlower_20250524T010000Z.jpg'
    image(source / 'images/zone1' / name)
    image(source / 'images/zone2' / name)
    items = scan_source(source)
    hash_identities(items)
    apply_dive_window(items, '2025-05-24T00:00:00Z', '2025-05-24T02:00:00Z')
    assert summarize_inventory(items)['sidecar_identity_collisions'] == []
    assert sum(bool(photo.duplicate_of) for photo in items) == 1
    result = stage_inventory(items, tmp_path / 'project', reserve_bytes=0, approved_token=approval_token(items))
    assert len([p for p in Path(result['images_root']).rglob('*') if p.is_file()]) == 1


def test_masks_are_associated_and_staged_with_original_filename(tmp_path):
    source = tmp_path / "source"
    photo = image(source / "images/camlower_20250524T010000Z.jpg")
    mask = image(photo.with_name(photo.name + ".mask.png"))
    items = scan_source(source)
    assert [x for x in items if x.kind == "mask"][0].mask_for == str(photo)
    verify_images(items)
    hash_identities(items)
    apply_dive_window(items, '2025-05-24T00:00:00Z', '2025-05-24T02:00:00Z')
    result = stage_inventory(items, tmp_path / "project", reserve_bytes=0, approved_token=approval_token(items))
    target = Path(result["images_root"]) / "cinema" / photo.name
    assert target.read_bytes() == photo.read_bytes()
    assert target.with_name(target.name + ".mask.png").read_bytes() == mask.read_bytes()
    assert target.stat().st_nlink == 1


def test_identical_zone_duplicates_collapse_but_different_bytes_block(tmp_path):
    source = tmp_path / "source"
    name = "camupper_20250524T010000Z.jpg"
    image(source / "images/zone1" / name)
    image(source / "images/zone2" / name)
    items = scan_source(source)
    hash_identities(items)
    assert sum(bool(item.duplicate_of) for item in items) == 1
    image(source / "images/zone2" / name, "black")
    items = scan_source(source)
    hash_identities(items)
    assert all("different image content" in item.exception for item in items)
    with pytest.raises(ValueError, match="unresolved"):
        stage_inventory(items, tmp_path / "project", reserve_bytes=0, approved_token=approval_token(items))


def test_outside_dive_window_and_unknown_filename_are_loud(tmp_path):
    source = tmp_path / "source"
    image(source / "images/camupper_20250524T010000Z.jpg")
    image(source / "images/unknown.jpg")
    items = scan_source(source)
    window = apply_dive_window(items, "2025-05-24T02:00:00Z", "2025-05-24T03:00:00Z")
    assert window["outside_count"] == 1
    assert all(item.exception for item in items)
    assert all(item.included for item in items)  # No unrecorded exclusion.


def test_mask_dimensions_and_orphans_block(tmp_path):
    source = tmp_path / "source"
    photo = image(source / "images/camlower_20250524T010000Z.jpg")
    image(photo.with_name(photo.name + ".mask.png"), size=(2, 2))
    image(source / "images/orphan.jpg.mask.png")
    items = scan_source(source)
    verify_images(items)
    masks = [item for item in items if item.kind == "mask"]
    assert all(item.exception for item in masks)
    assert len([item for item in items if item.kind == "image"]) == 1


def prepared(tmp_path):
    source = tmp_path / 'source'
    photo = image(source / 'images/camupper_20250524T010000Z.jpg')
    items = scan_source(source)
    apply_dive_window(items, '2025-05-24T00:00:00Z', '2025-05-24T02:00:00Z')
    hash_identities(items)
    return source, photo, items


def test_discovery_covers_new_trees_and_recognized_names_outside_images(tmp_path):
    source = tmp_path / 'source'
    image(source / 'images/upper/camupper_20250524T010000Z.jpg')
    image(source / 'new_delivery/lower/camlower_20250524T010001Z.jpg')
    image(source / 'cruise/raw/still_cam/unregistered_20250524T010002Z.jpg')
    image(source / 'report/thumbnail.jpg')
    image(source / 'images/._camupper_20250524T010000Z.jpg')
    items = scan_source(source)
    assert len(items) == 3
    assert {im.camera for im in items} == {'starboard', 'cinema', ''}
    assert all('thumbnail' not in im.path and '._' not in im.path for im in items)


@pytest.mark.parametrize('change', ['new_image', 'new_folder', 'noise_file', 'remove', 'rename', 'edit'])
def test_whole_tree_fingerprint_invalidates_review(tmp_path, change):
    source, photo, items = prepared(tmp_path)
    token = approval_token(items)
    if change == 'new_image':
        image(source / 'later/cammid_20250524T010005Z.jpg')
    elif change == 'new_folder':
        (source / 'new_empty_directory').mkdir()
    elif change == 'noise_file':
        (source / 'readme.txt').write_text('new source delivery')
    elif change == 'remove':
        photo.unlink()
    elif change == 'rename':
        photo.rename(photo.with_name('renamed.jpg'))
    else:
        photo.write_bytes(b'changed')
    with pytest.raises(ValueError, match='Source tree changed'):
        stage_inventory(items, tmp_path / 'project', reserve_bytes=0, approved_token=token)
    assert not (tmp_path / 'project').exists()


def test_change_during_scan_is_detected(tmp_path, monkeypatch):
    from modules import source_inventory as inventory
    source = tmp_path / 'source'
    image(source / 'images/camupper_20250524T010000Z.jpg')
    original = inventory.camera_registry.family
    changed = False

    def family(name):
        nonlocal changed
        if not changed:
            (source / 'arrived_during_scan').mkdir()
            changed = True
        return original(name)

    monkeypatch.setattr(inventory.camera_registry, 'family', family)
    with pytest.raises(ValueError, match='Source tree changed'):
        scan_source(source)


def test_change_during_staging_fails_without_success_receipt(tmp_path):
    source, _, items = prepared(tmp_path)
    token = approval_token(items)

    def progress(*args):
        (source / 'new_file.txt').write_text('changed while copying')

    with pytest.raises(ValueError, match='Source tree changed'):
        stage_inventory(items, tmp_path / 'project', reserve_bytes=0, approved_token=token, progress=progress)


def test_approval_binds_selection_window_and_content(tmp_path):
    _, _, items = prepared(tmp_path)
    token = approval_token(items)
    items[0].included = False
    assert approval_token(items) != token
    with pytest.raises(ValueError, match='explicitly confirmed'):
        stage_inventory(items, tmp_path / 'project', reserve_bytes=0, approved_token=token)
    items[0].included = True
    apply_dive_window(items, '2025-05-24T00:00:01Z', '2025-05-24T02:00:00Z')
    assert approval_token(items) != token


def test_unhashed_summary_does_not_pretend_duplicates_are_known(tmp_path):
    source = tmp_path / 'source'
    image(source / 'camupper_20250524T010000Z.jpg')
    report = summarize_inventory(scan_source(source))
    assert report['approval_token'] is None
    assert report['cameras']['starboard']['unique'] is None
    assert report['cameras']['starboard']['identical_duplicates'] is None


def test_summary_counts_all_name_collision_members_without_losing_date_errors(tmp_path):
    source = tmp_path / 'source'
    name = 'camupper_20250230T010000Z.jpg'
    for folder, color in [('a', 'white'), ('b', 'white'), ('c', 'black')]:
        image(source / 'images' / folder / name, color)
    items = scan_source(source)
    apply_dive_window(items, '2025-05-24T00:00:00Z', '2025-05-24T02:00:00Z')
    hash_identities(items)
    report = summarize_inventory(items)['cameras']['starboard']
    assert (report['total'], report['unique'], report['identical_duplicates'], report['conflicting_names']) == (3, 2, 1, 1)
    assert report['invalid_timestamp'] == 3
    assert all('No valid UTC' in im.exception and 'different image content' in im.exception for im in items)
    assert all(not im.timestamp_utc for im in items)


@pytest.mark.parametrize('name', ['camupper_missing.jpg', 'camupper_20251301T010000Z.jpg'])
def test_missing_invalid_dates_never_become_epoch(tmp_path, name):
    source = tmp_path / 'source'
    image(source / 'images' / name)
    item = scan_source(source)[0]
    assert item.timestamp_utc == ''
    assert item.window_status == 'invalid_timestamp'


def test_repeated_window_application_is_idempotent(tmp_path):
    _, _, items = prepared(tmp_path)
    for _ in range(2):
        apply_dive_window(items, '2025-05-24T01:01:00Z', '2025-05-24T02:00:00Z')
    assert items[0].exception.count('outside the recorded') == 1
    apply_dive_window(items, '2025-05-24T00:00:00Z', '2025-05-24T02:00:00Z')
    assert items[0].exception == ''


def test_mask_directory_association_and_orphan_summary(tmp_path):
    source = tmp_path / 'source'
    image(source / 'images/camlower_20250524T010000Z.jpeg')
    image(source / 'images/.mask/camlower_20250524T010000Z.png')
    image(source / 'images/camlower_20250524T010002Z.jpeg.mask.png')
    items = scan_source(source)
    masks = [im for im in items if im.kind == 'mask']
    assert sum(bool(im.mask_for) for im in masks) == 1
    report = summarize_inventory(items)['cameras']['cinema']
    assert report['masks'] == 2 and report['unmatched_masks'] == 1


def test_float_map_is_copied_without_conversion(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    path = source / 'numeric.tif'
    Image.new('F', (4, 3), -1234.5).save(path)
    items = scan_source(source)
    assert items[0].kind == 'map'
    hash_identities(items)
    stage_inventory(items, tmp_path / 'project', reserve_bytes=0, approved_token=approval_token(items))
    assert path.read_bytes() == (tmp_path / 'project/numeric.tif').read_bytes()
    with Image.open(tmp_path / 'project/numeric.tif') as result:
        assert result.mode == 'F' and result.getpixel((0, 0)) == -1234.5


def test_source_inventory_roundtrip_retains_guard(tmp_path):
    from dataclasses import asdict
    from modules.source_inventory import SourceItem
    _, _, items = prepared(tmp_path)
    restored = SourceInventory([SourceItem(**json.loads(json.dumps(asdict(im)))) for im in items],
                               source_root=items.source_root, fingerprint=items.source_fingerprint,
                               dive_window=items.dive_window)
    assert approval_token(restored) == approval_token(items)
    assert_source_unchanged(restored)


def test_cached_copy_cannot_hide_changed_source_with_same_mtime(tmp_path):
    source = tmp_path / 'source.bin'
    source.write_bytes(b'aaaa')
    from modules.source_inventory import file_hash
    digest = file_hash(source)
    target = tmp_path / 'target.bin'
    target.write_bytes(b'aaaa')
    before = source.stat()
    source.write_bytes(b'bbbb')
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(ValueError, match='Source changed'):
        copy_verified(source, target, expected_hash=digest, reserve_bytes=0)
    assert target.read_bytes() == b'aaaa'


def test_conflicting_duplicate_masks_refused_before_any_copy(tmp_path):
    source = tmp_path / 'source'
    for folder, color in [('a', 'white'), ('b', 'black')]:
        photo = image(source / 'images' / folder / 'camlower_20250524T010000Z.jpg')
        image(photo.with_name(photo.name + '.mask.png'), color)
    items = scan_source(source)
    apply_dive_window(items, '2025-05-24T00:00:00Z', '2025-05-24T02:00:00Z')
    hash_identities(items)
    with pytest.raises(ValueError, match='Conflicting content'):
        stage_inventory(items, tmp_path / 'project', reserve_bytes=0, approved_token=approval_token(items))
    assert not (tmp_path / 'project').exists()


def callback_inventory(tmp_path):
    source = tmp_path / 'callbacks'
    photo = image(source / 'images/camlower_20250524T010000Z.jpg')
    image(photo.with_name(photo.name + '.mask.png'))
    image(source / 'images/camupper_20250524T010001Z.jpg')
    (source / 'numeric.tif').write_bytes(b'map bytes, hashing only')
    photo.with_suffix('.xmp').write_text('<metadata/>')
    return scan_source(source)


def test_hash_callback_progress_includes_maps_masks_and_sidecars(tmp_path):
    items = callback_inventory(tmp_path)
    events = []
    hash_identities(items, cancelled=lambda: False, progress=lambda *event: events.append(event))
    assert events == [(i + 1, len(items), item.path) for i, item in enumerate(items)]
    assert items.hashing_complete is True
    assert all(item.sha256 for item in items)


def test_hash_cancel_retains_completed_digests_and_resume_skips_them(tmp_path, monkeypatch):
    from modules import source_inventory as inventory
    items = callback_inventory(tmp_path)
    events = []
    with pytest.raises(InterruptedError):
        hash_identities(items, cancelled=lambda: bool(events), progress=lambda *event: events.append(event))
    assert len(events) == 1 and items[0].sha256
    assert all(not item.sha256 for item in items[1:])
    assert summarize_inventory(items)['approval_token'] is None
    real_hash = inventory.file_hash
    reads = []

    def counted(path, **kwargs):
        reads.append(str(path))
        return real_hash(path, **kwargs)

    monkeypatch.setattr(inventory, 'file_hash', counted)
    hash_identities(items, resume=True)
    assert reads == [item.path for item in items[1:]]
    assert items.hashing_complete is True
    assert approval_token(items)


def test_hash_resume_still_refuses_source_change(tmp_path):
    items = callback_inventory(tmp_path)
    events = []
    with pytest.raises(InterruptedError):
        hash_identities(items, cancelled=lambda: bool(events), progress=lambda *event: events.append(event))
    Path(items[0].path).write_bytes(b'changed')
    with pytest.raises(ValueError, match='Source tree changed'):
        hash_identities(items, resume=True)


def test_hash_default_rehashes_even_previously_completed_files(tmp_path, monkeypatch):
    from modules import source_inventory as inventory
    _, _, items = prepared(tmp_path)
    reads = []
    original = inventory.file_hash

    def counted(path, **kwargs):
        reads.append(str(path))
        return original(path, **kwargs)

    monkeypatch.setattr(inventory, 'file_hash', counted)
    hash_identities(items)
    assert reads == [items[0].path]


def test_file_hash_cancellation_inside_large_file_leaves_no_digest(tmp_path):
    from modules.source_inventory import file_hash
    path = tmp_path / 'large.bin'
    path.write_bytes(b'x' * (9 * 1024 * 1024))
    calls = 0

    def cancelled():
        nonlocal calls
        calls += 1
        return calls >= 4

    with pytest.raises(InterruptedError):
        file_hash(path, cancelled=cancelled)
    assert calls == 4 and path.stat().st_size == 9 * 1024 * 1024


def test_cancel_at_final_hash_progress_does_not_allow_approval(tmp_path):
    _, _, items = prepared(tmp_path)
    events = []
    with pytest.raises(InterruptedError):
        hash_identities(items, cancelled=lambda: bool(events), progress=lambda *event: events.append(event))
    assert all(item.sha256 for item in items)
    assert items.hashing_complete is False
    assert summarize_inventory(items)['approval_token'] is None
    with pytest.raises(ValueError, match='fully hashed'):
        approval_token(items)


def test_verification_progress_counts_only_included_images_and_masks(tmp_path):
    items = callback_inventory(tmp_path)
    events = []
    verify_images(items, cancelled=lambda: False, progress=lambda *event: events.append(event))
    eligible = [item for item in items if item.kind in ('image', 'mask') and item.included]
    assert events == [(i + 1, len(eligible), item.path) for i, item in enumerate(eligible)]
    assert items.verification_complete is True


def test_verification_cancel_is_not_an_unreadable_image_error_and_can_retry(tmp_path):
    items = callback_inventory(tmp_path)
    hash_identities(items)
    events = []
    with pytest.raises(InterruptedError):
        verify_images(items, cancelled=lambda: bool(events), progress=lambda *event: events.append(event))
    assert items.verification_complete is False
    assert all('Unreadable' not in item.exception for item in items)
    assert summarize_inventory(items)['approval_token'] is None
    verify_images(items)
    assert items.verification_complete is True and approval_token(items)


@pytest.mark.parametrize('operation', [verify_images, hash_identities])
def test_callback_failure_propagates_and_invalidates_completion(tmp_path, operation):
    items = callback_inventory(tmp_path)

    def failed(*args):
        raise RuntimeError('UI disconnected')

    with pytest.raises(RuntimeError, match='UI disconnected'):
        operation(items, progress=failed)
    assert summarize_inventory(items)['approval_token'] is None


@pytest.mark.parametrize('operation', [verify_images, hash_identities])
def test_pre_cancelled_work_does_not_report_progress(tmp_path, operation):
    items = callback_inventory(tmp_path)
    events = []
    with pytest.raises(InterruptedError):
        operation(items, cancelled=lambda: True, progress=lambda *event: events.append(event))
    assert events == []


def selection_inventory(tmp_path):
    source = tmp_path / 'selection-source'
    for second in (0, 1):
        photo = image(source / f'images/camlower_20250524T01000{second}Z.jpg')
        image(photo.with_name(photo.name + '.mask.png'))
    items = scan_source(source)
    apply_dive_window(items, '2025-05-24T00:00:00Z', '2025-05-24T02:00:00Z')
    hash_identities(items)
    return items


def test_distinct_approved_selection_trees_preserve_shared_raw_and_old_selection(tmp_path):
    items = selection_inventory(tmp_path)
    project = tmp_path / 'project'
    first_token = approval_token(items)
    first = stage_inventory(items, project, reserve_bytes=0, approved_token=first_token,
                            images_relative_path=f'proc/selections/{first_token}/images')
    first_root = Path(first['images_root'])
    old_files = {str(path): path.read_bytes() for path in first_root.rglob('*') if path.is_file()}
    raw_files = {str(path): path.read_bytes() for path in (project / 'raw/imagery').rglob('*') if path.is_file()}
    for item in items:
        if '010001Z' in item.path:
            item.included = False
    second_token = approval_token(items)
    assert second_token != first_token
    second = stage_inventory(items, project, reserve_bytes=0, approved_token=second_token,
                             images_relative_path=f'proc/selections/{second_token}/images')
    second_files = [p for p in Path(second['images_root']).rglob('*') if p.is_file()]
    assert len(second_files) == 2  # Kept image and its mask only.
    assert all('010000Z' in path.name for path in second_files)
    assert second['images_relative_path'] == f'proc/selections/{second_token}/images'
    assert all(Path(path).read_bytes() == data for path, data in old_files.items())
    assert all(Path(path).read_bytes() == data for path, data in raw_files.items())


def test_default_tree_refuses_stale_geometry_after_exclusion_without_deleting(tmp_path):
    items = selection_inventory(tmp_path)
    project = tmp_path / 'project'
    first = stage_inventory(items, project, reserve_bytes=0, approved_token=approval_token(items))
    assert first['images_root'] == str(project / 'proc/images')
    original = {str(p): p.read_bytes() for p in Path(first['images_root']).rglob('*') if p.is_file()}
    for item in items:
        if '010001Z' in item.path:
            item.included = False
    with pytest.raises(FileExistsError, match='Unmanifested file'):
        stage_inventory(items, project, reserve_bytes=0, approved_token=approval_token(items))
    assert all(Path(path).read_bytes() == data for path, data in original.items())


@pytest.mark.parametrize('relative', ['proc', 'raw/images', '../proc/images', '/proc/images',
                                    'F:/proc/images', 'proc/../raw/images', 'proc//images',
                                    'proc/./images', 'proc/images/', 'proc\\images',
                                    'proc/images:stream', 'proc/NUL/images', 'proc/images.'])
def test_invalid_selection_path_rejected_before_any_copy(tmp_path, relative):
    _, _, items = prepared(tmp_path)
    project = tmp_path / 'project'
    with pytest.raises(ValueError, match='images_relative_path'):
        stage_inventory(items, project, reserve_bytes=0, approved_token=approval_token(items),
                        images_relative_path=relative)
    assert not project.exists()


@pytest.mark.parametrize('name', ['unmanifested.jpg', 'unmanifested.jpg.mask.png', 'unexpected.xmp'])
def test_existing_unmanifested_selection_file_blocks_before_raw_writes(tmp_path, name):
    _, _, items = prepared(tmp_path)
    project = tmp_path / 'project'
    root = project / 'proc/selections/reviewed/images'
    root.mkdir(parents=True)
    unexpected = root / name
    unexpected.write_bytes(b'old input')
    with pytest.raises(FileExistsError, match='Unmanifested'):
        stage_inventory(items, project, reserve_bytes=0, approved_token=approval_token(items),
                        images_relative_path='proc/selections/reviewed/images')
    assert unexpected.read_bytes() == b'old input'
    assert not (project / 'raw').exists()


def test_conflicting_existing_mask_blocks_before_raw_writes(tmp_path):
    items = selection_inventory(tmp_path)
    project = tmp_path / 'project'
    mask = next(item for item in items if item.kind == 'mask')
    existing = project / 'proc/images' / mask.camera / Path(mask.path).name
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b'different mask')
    with pytest.raises(FileExistsError, match='Conflicting existing image/mask'):
        stage_inventory(items, project, reserve_bytes=0, approved_token=approval_token(items))
    assert existing.read_bytes() == b'different mask'
    assert not (project / 'raw').exists()


def test_geometry_arriving_during_staging_prevents_success(tmp_path):
    _, _, items = prepared(tmp_path)
    project = tmp_path / 'project'

    def inject(*args):
        (project / 'proc/images/unmanifested.jpg').write_bytes(b'arrived during copy')

    with pytest.raises(FileExistsError, match='Unmanifested'):
        stage_inventory(items, project, reserve_bytes=0, approved_token=approval_token(items), progress=inject)
    assert (project / 'proc/images/unmanifested.jpg').exists()


def test_mask_modified_during_staging_is_detected_by_final_census(tmp_path):
    items = selection_inventory(tmp_path)
    project = tmp_path / 'project'

    def corrupt(done, total, path):
        if done == total:
            mask = next((project / 'proc/images').rglob('*.mask.png'))
            mask.write_bytes(b'changed after its copy was verified')

    with pytest.raises(FileExistsError, match='Conflicting existing image/mask'):
        stage_inventory(items, project, reserve_bytes=0, approved_token=approval_token(items), progress=corrupt)


def test_matching_selection_can_resume_without_overwriting(tmp_path):
    _, _, items = prepared(tmp_path)
    project = tmp_path / 'project'
    token = approval_token(items)
    relative = f'proc/selections/{token}/images'
    first = stage_inventory(items, project, reserve_bytes=0, approved_token=token, images_relative_path=relative)
    output = Path(first['outputs'][0])
    before = output.stat().st_mtime_ns
    second = stage_inventory(items, project, reserve_bytes=0, approved_token=token, images_relative_path=relative)
    assert first == second
    assert output.stat().st_mtime_ns == before


def test_redirected_selection_parent_is_refused(tmp_path, monkeypatch):
    _, _, items = prepared(tmp_path)
    project = tmp_path / 'project'
    monkeypatch.setattr(Path, 'is_junction', lambda path: path == project / 'proc/selections')
    with pytest.raises(ValueError, match='redirected'):
        stage_inventory(items, project, reserve_bytes=0, approved_token=approval_token(items),
                        images_relative_path='proc/selections/test/images')
    assert not project.exists()


def test_expected_geometry_removed_during_staging_is_not_reported_complete(tmp_path):
    _, _, items = prepared(tmp_path)
    project = tmp_path / 'project'

    def remove_copied_file(*args):
        next((project / 'proc/images').rglob('*.jpg')).unlink()

    with pytest.raises(ValueError, match='selection tree is incomplete'):
        stage_inventory(items, project, reserve_bytes=0, approved_token=approval_token(items),
                        progress=remove_copied_file)


def test_file_as_selection_parent_blocks_before_raw_writes(tmp_path):
    _, _, items = prepared(tmp_path)
    project = tmp_path / 'project'
    (project / 'proc').mkdir(parents=True)
    (project / 'proc/selections').write_text('existing file')
    with pytest.raises(ValueError, match='not a directory'):
        stage_inventory(items, project, reserve_bytes=0, approved_token=approval_token(items),
                        images_relative_path='proc/selections/test/images')
    assert not (project / 'raw').exists()
