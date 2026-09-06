"""
The export census must expect exactly the formats the workflow was asked to
produce.

`ExportDeliverables.bat` skips the dense PLY when RS_EXPORT_SKIP_PLY is set,
because its source model does not survive GenerateModel in this build (see
FINDINGS 2026-09-01). Without the census agreeing, a run whose OBJ and FBX were
both complete failed with "1 of 3 expected deliverable folder(s) hold no file:
zone_all_c17/ply".

The census must keep its teeth for every format that WAS requested - that guard
is the reason do-nothing exports get caught at all.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from modules.export_deliverables import (EXPORT_KINDS, expected_kinds,
                                         missing_exports)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv('RS_EXPORT_SKIP_PLY', raising=False)


def test_default_expects_all_three():
    assert expected_kinds() == EXPORT_KINDS
    assert 'ply' in expected_kinds()


def test_skip_ply_drops_only_ply(monkeypatch):
    monkeypatch.setenv('RS_EXPORT_SKIP_PLY', '1')
    assert expected_kinds() == ('obj', 'fbx')


def _make(tmp_path, comp, kinds):
    for k in kinds:
        d = tmp_path / comp / k
        d.mkdir(parents=True)
        (d / f'{comp}.{k}').write_text('x', encoding='utf-8')
    return str(tmp_path)


def test_missing_ply_is_reported_by_default(tmp_path):
    root = _make(tmp_path, 'c1', ('obj', 'fbx'))
    assert missing_exports(root, ['c1']) == ['c1/ply']


def test_missing_ply_is_not_reported_when_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv('RS_EXPORT_SKIP_PLY', '1')
    root = _make(tmp_path, 'c1', ('obj', 'fbx'))
    assert missing_exports(root, ['c1']) == []


def test_census_still_catches_a_missing_obj_when_ply_is_skipped(tmp_path, monkeypatch):
    # The teeth must survive the exemption: skipping PLY must not blind the
    # census to a do-nothing OBJ export, which is the failure it exists for.
    monkeypatch.setenv('RS_EXPORT_SKIP_PLY', '1')
    root = _make(tmp_path, 'c1', ('fbx',))
    assert missing_exports(root, ['c1']) == ['c1/obj']


def test_empty_files_do_not_count_as_produced(tmp_path, monkeypatch):
    monkeypatch.setenv('RS_EXPORT_SKIP_PLY', '1')
    for k in ('obj', 'fbx'):
        d = tmp_path / 'c1' / k
        d.mkdir(parents=True)
        (d / f'c1.{k}').write_text('', encoding='utf-8')
    assert sorted(missing_exports(str(tmp_path), ['c1'])) == ['c1/fbx', 'c1/obj']
