"""Offline native alignment approval boundary; no CLI construction or markers."""
import inspect
from pathlib import Path

import pytest

from modules.realityscan_interface import realityscan_interface as interface
from modules import project_occlusion


KEYS = ('RS_SELECTION_MANIFEST', 'RS_OCCLUSION_MANIFEST', 'RS_OCCLUSION_MANIFEST_SHA256')


@pytest.fixture
def zone(tmp_path, monkeypatch):
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)
    path = tmp_path / 'batched_images_by_zone' / 'zone_1'
    path.mkdir(parents=True)
    return path


def test_legacy_probe_does_not_enter_project_gate(zone, monkeypatch):
    monkeypatch.setattr(project_occlusion, 'validate_external', lambda *a, **k: pytest.fail('Unexpected project gate'))
    assert interface.validate_project_occlusion(zone) is None


@pytest.mark.parametrize('missing', KEYS)
@pytest.mark.parametrize('value', ['', '   '])
def test_selected_project_requires_complete_environment(zone, monkeypatch, missing, value):
    for key in KEYS:
        monkeypatch.setenv(key, value if key == missing else 'approved')
    with pytest.raises(ValueError, match=missing):
        interface.validate_project_occlusion(zone)


def test_actual_whole_batch_parent_is_passed_and_rechecked(zone, monkeypatch):
    for key, value in zip(KEYS, ('selection.json', 'masks.json', 'a' * 64)):
        monkeypatch.setenv(key, value)
    calls = []

    def validate(*args, **kwargs):
        calls.append((args, kwargs))
        if len(calls) > 1:
            raise ValueError('Actual batch masks changed')
        return {'decision': 'applied', 'project_root': str(zone.parent.parent)}

    monkeypatch.setattr(project_occlusion, 'validate_external', validate)
    assert interface.validate_project_occlusion(zone)['decision'] == 'applied'
    assert calls[0] == (('masks.json', 'a' * 64, 'selection.json'), {'batch_root': zone.parent.resolve()})
    with pytest.raises(ValueError, match='changed'):
        interface.validate_project_occlusion(zone)


def test_native_gate_is_before_preparation_and_immediately_before_launch():
    # Assert the two real call sites, without executing unrelated runtime work.
    classes = [item for item in vars(interface).values() if inspect.isclass(item)]
    cls = next(item for item in classes if any(name.endswith('__align_zone') for name in vars(item)))
    method = next(value for name, value in vars(cls).items() if name.endswith('__align_zone'))
    source = inspect.getsource(method)
    gate = 'validate_project_occlusion(input_folder)'
    assert source.count(gate) == 2
    assert source.index(gate) < source.index('prepare_input_prior_contract(')
    assert gate + '\n        result = self.cli.run_batch_script(' in source
