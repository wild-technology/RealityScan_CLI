"""Fresh batch calibration contracts; no RealityScan or source-side writes."""
import logging
import json
from dataclasses import replace
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from modules import camera_registry
from modules.image_batcher.batch_directory import BatchDirectory


@pytest.fixture
def batch(tmp_path):
    module = BatchDirectory(logging.getLogger(__name__))
    module.params = module.get_parameters()
    module.params['batch_xmp_priors'].set_value(True)
    source = tmp_path / 'source'
    source.mkdir()
    target = tmp_path / 'batch'
    target.mkdir()
    return module, source, target


def copy(batch, names):
    module, source, target = batch
    return module._BatchDirectory__copy_files(str(source), str(target), names)


def test_native_registry_calibration_exact_geometry_coverage_excludes_masks(batch):
    module, source, target = batch
    for name in ('cammid_001.jpg', 'camupper_001.jpg'):
        (source / name).write_bytes(name.encode())
    (source / 'cammid_001.jpg.mask.png').write_bytes(b'approved mask')
    baseline = {p.name: p.read_bytes() for p in source.iterdir()}
    assert copy(batch, ['cammid_001.jpg', 'camupper_001.jpg']) == (2, 0)
    sidecars = list(target.rglob('*.xmp'))
    assert len(sidecars) == 2
    for path in sidecars:
        camera = camera_registry.identify(path.with_suffix('.jpg').name)
        camera_registry.validate_calibration_xmp(path.read_text(), camera)
        description = ET.fromstring(path.read_text()).find('.//{http://www.w3.org/1999/02/22-rdf-syntax-ns#}Description')
        ns = '{http://www.capturingreality.com/ns/xcr/1.1#}'
        assert float(description.attrib[ns + 'FocalLength35mm']) == pytest.approx(camera.focal_length_35mm)
        assert description.attrib[ns + 'CalibrationGroup'] == camera.calibration_group
    assert len(list(target.rglob('*.mask.png'))) == 1
    assert {p.name: p.read_bytes() for p in source.iterdir()} == baseline
    assert copy(batch, ['cammid_001.jpg', 'camupper_001.jpg']) == (2, 0)


def test_mask_free_batch_needs_no_source_masks(batch):
    _, source, target = batch
    (source / 'cammid_001.jpg').write_bytes(b'pixels')
    assert copy(batch, ['cammid_001.jpg']) == (1, 0)
    assert len(list(target.rglob('*.xmp'))) == 1


@pytest.mark.parametrize('fault', ['unknown', 'missing', 'duplicate', 'stem_collision', 'extra_xmp'])
def test_incomplete_or_ambiguous_calibration_refuses(batch, fault):
    _, source, target = batch
    name = 'unrecognized.jpg' if fault == 'unknown' else 'cammid_001.jpg'
    (source / name).write_bytes(b'pixels')
    names = [name]
    if fault == 'missing':
        names.append('cammid_missing.jpg')
    elif fault == 'duplicate':
        names.append(name)
    elif fault == 'stem_collision':
        (source / 'cammid_001.png').write_bytes(b'other pixels')
        names.append('cammid_001.png')
    elif fault == 'extra_xmp':
        (target / 'unexpected.xmp').write_text('stale')
    with pytest.raises(ValueError):
        copy(batch, names)


def test_calibration_write_failure_propagates(batch, monkeypatch):
    _, source, _ = batch
    (source / 'cammid_001.jpg').write_bytes(b'pixels')
    original = Path.open
    def failing(path, *args, **kwargs):
        if path.suffix == '.xmp' and args and args[0] == 'x':
            raise PermissionError('simulated sidecar write failure')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', failing)
    with pytest.raises(PermissionError, match='simulated'):
        copy(batch, ['cammid_001.jpg'])


def test_existing_pose_sidecar_refused_and_preserved(batch):
    module, _, target = batch
    path = target / 'cammid_001.xmp'
    path.write_text('<legacy pose="preserve"/>')
    with pytest.raises(ValueError, match='pose-bearing'):
        module._BatchDirectory__generate_xmp_sidecar('cammid_001.jpg', str(target), 'cammid')
    assert path.read_text() == '<legacy pose="preserve"/>'


def test_native_calibration_resume_binds_profiles_and_rechecks_sidecars(batch, monkeypatch):
    module, source, target = batch
    monkeypatch.setattr(module, '_BatchDirectory__get_input_dir', lambda: str(source))
    monkeypatch.setattr(module, '_require_selection_manifest', lambda: None)
    (source / 'cammid_001.jpg').write_bytes(b'pixels')
    zone = target / 'zone_1'
    zone.mkdir()
    copy((module, source, zone), ['cammid_001.jpg'])
    fingerprint = module._input_fingerprint('')
    (target / module.FINGERPRINT_NAME).write_text(json.dumps(dict(fingerprint, status='complete')))
    assert module._check_reuse_is_safe(str(target), '') == (True, None)
    camera = camera_registry.identify('cammid_001.jpg')
    with monkeypatch.context() as patch:
        patch.setitem(camera_registry.CAMERAS, camera.key,
                      replace(camera, focal_length_35mm=camera.focal_length_35mm + 1))
        assert not module._check_reuse_is_safe(str(target), '')[0]
    next(zone.rglob('*.xmp')).unlink()
    ok, reason = module._check_reuse_is_safe(str(target), '')
    assert not ok and 'calibration coverage' in reason
    legacy = dict(fingerprint, status='complete')
    del legacy['native_calibration']
    (target / module.FINGERPRINT_NAME).write_text(json.dumps(legacy))
    assert not module._check_reuse_is_safe(str(target), '')[0]
