#!/usr/bin/env python3
"""What is left to export is read from disk - and read correctly.

Ported with modules/export_remaining.py from NA165/H2060's
_agent/export/remaining.py, which drove the 39-component export's retry loop
(2026-09-14). Every case below is a way that helper, or its first version,
got "done" wrong:

  - it checked the exact stem and matched nothing, because a by-parts export
    names its part zone_1_c40_0000000.obj - so all 39 read "to do" forever;
  - a zero-byte part is what a disk-full export leaves behind;
  - the FBX .rsInfo is the proof BOTH mesh exports finished;
  - a textured OBJ without its .mtl is an untextured OBJ;
  - and, new with the JPG re-export: a preset key RealityScan ignores fails
    silently, so the textures themselves are part of "done".

Hermetic: fixture trees in tmp_path. No RealityScan.

Run:  python -m pytest testing/test_export_remaining.py
"""
from __future__ import annotations

import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO_ROOT)

from modules import export_remaining as er  # noqa: E402

JPEG = b'\xff\xd8\xff\xe0jfif'
PNG = b'\x89PNG\r\n\x1a\n'


def _meshes(root, stem, tex='jpg', parts=1, skip=(), empty=()):
    """A by-parts export as ExportDeliverables writes it."""
    body = JPEG if tex == 'jpg' else PNG
    for sub in ('obj', 'fbx'):
        (root / stem / sub).mkdir(parents=True, exist_ok=True)
    files = {}
    for i in range(parts):
        part = f'{stem}_{i:07d}'
        files[f'obj/{part}.obj'] = b'mtllib x\nv 0 0 0\n'
        files[f'obj/{part}.mtl'] = (f'map_Kd {stem}_u1_v1_diffuse.{tex}\n'
                                    f'map_Bump {stem}_u1_v1_normal.{tex}\n').encode()
        files[f'obj/{part}.obj.rsInfo'] = b'<Model/>'
        files[f'fbx/{part}.fbx'] = b'fbx'
        files[f'fbx/{part}.fbx.rsInfo'] = b'<Model/>'
    for sub in ('obj', 'fbx'):
        files[f'{sub}/{stem}_u1_v1_diffuse.{tex}'] = body
        files[f'{sub}/{stem}_u1_v1_normal.{tex}'] = body
    for rel, data in files.items():
        if rel in skip:
            continue
        (root / stem / rel).write_bytes(b'' if rel in empty else data)


def _ply(root, stem, rsinfo=True):
    d = root / stem / 'ply'
    d.mkdir(parents=True, exist_ok=True)
    (d / f'{stem}_dense.ply').write_bytes(b'ply')
    if rsinfo:
        (d / f'{stem}_dense.ply.rsInfo').write_bytes(b'<Model/>')


def test_by_parts_export_under_the_suffixed_stem_is_done(tmp_path):
    _meshes(tmp_path, 'zone_1_c40_L', parts=3)
    assert er.component_done(str(tmp_path), 'zone_1_c40', 'meshes', '_L', 'jpg')


def test_the_unsuffixed_generation_does_not_count(tmp_path):
    """The old PNG tree must never satisfy the new pass."""
    _meshes(tmp_path, 'zone_1_c40', tex='png')
    assert not er.component_done(str(tmp_path), 'zone_1_c40', 'meshes', '_L')


@pytest.mark.parametrize('rel', ['obj/zone_1_c40_L_0000000.mtl',
                                 'fbx/zone_1_c40_L_0000000.fbx.rsInfo',
                                 'obj/zone_1_c40_L_0000000.obj.rsInfo'])
def test_a_missing_marker_or_material_is_not_done(tmp_path, rel):
    _meshes(tmp_path, 'zone_1_c40_L', skip={rel})
    assert not er.component_done(str(tmp_path), 'zone_1_c40', 'meshes', '_L')


def test_one_empty_part_is_not_done(tmp_path):
    """Every part must have content, not just the first."""
    _meshes(tmp_path, 'zone_1_c40_L', parts=3,
            empty={'obj/zone_1_c40_L_0000002.obj'})
    assert not er.component_done(str(tmp_path), 'zone_1_c40', 'meshes', '_L')


def test_png_textures_fail_a_jpg_pass(tmp_path):
    _meshes(tmp_path, 'zone_1_c40_L', tex='png')
    assert er.component_done(str(tmp_path), 'zone_1_c40', 'meshes', '_L')
    assert not er.component_done(str(tmp_path), 'zone_1_c40', 'meshes', '_L', 'jpg')
    assert er.texture_problems(str(tmp_path), 'zone_1_c40', '_L', 'jpg')


def test_a_jpg_name_on_non_jpeg_bytes_is_caught(tmp_path):
    _meshes(tmp_path, 'zone_1_c40_L')
    (tmp_path / 'zone_1_c40_L' / 'obj' / 'zone_1_c40_L_u1_v1_diffuse.jpg').write_bytes(PNG)
    problems = er.texture_problems(str(tmp_path), 'zone_1_c40', '_L', 'jpg')
    assert any('not a JPEG' in p for p in problems)


def test_the_fbx_copy_of_each_texture_is_required(tmp_path):
    _meshes(tmp_path, 'zone_1_c40_L', skip={'fbx/zone_1_c40_L_u1_v1_normal.jpg'})
    problems = er.texture_problems(str(tmp_path), 'zone_1_c40', '_L', 'jpg')
    assert problems == ['zone_1_c40_L: fbx/zone_1_c40_L_u1_v1_normal.jpg missing']


def test_ply_pass_needs_the_sidecar(tmp_path):
    _ply(tmp_path, 'zone_1_c40_L', rsinfo=False)
    assert not er.component_done(str(tmp_path), 'zone_1_c40', 'ply', '_L')
    _ply(tmp_path, 'zone_1_c40_L')
    assert er.component_done(str(tmp_path), 'zone_1_c40', 'ply', '_L')


def test_cli_writes_a_crlf_list_and_reports_remaining(tmp_path, capsys):
    exports = tmp_path / 'exports'
    _meshes(exports, 'c1_L')
    names = tmp_path / 'all.names'
    names.write_text('c1\nc2\nc3\n', encoding='utf-8')
    out = tmp_path / 'left.names'
    rc = er.main(['--exports', str(exports), '--names', str(names),
                  '--out', str(out), '--suffix', '_L', '--textures', 'jpg'])
    assert rc == 0
    assert out.read_bytes() == b'c2\r\nc3\r\n'
    printed = capsys.readouterr().out.splitlines()
    assert 'REMAINING=2' in printed, 'the driver parses this line exactly'


def test_cli_exit_3_means_the_pass_is_complete(tmp_path):
    exports = tmp_path / 'exports'
    _ply(exports, 'c1_L')
    names = tmp_path / 'all.names'
    names.write_text('c1\n', encoding='utf-8')
    out = tmp_path / 'left.names'
    assert er.main(['--exports', str(exports), '--names', str(names),
                    '--out', str(out), '--suffix', '_L', '--pass', 'ply']) == 3
    assert out.read_bytes() == b''


def test_report_input_is_successful_models_smallest_first(tmp_path):
    report = tmp_path / 'models_report.json'
    report.write_text(json.dumps({'models': [
        {'component': 'big', 'cameras': 900, 'success': True},
        {'component': 'failed', 'cameras': 10, 'success': False},
        {'component': 'small', 'cameras': 52, 'success': True}]}),
        encoding='utf-8')
    assert er.components_from_report(str(report)) == ['small', 'big']


def test_cli_refuses_a_hostile_suffix(tmp_path):
    names = tmp_path / 'n'
    names.write_text('c1\n', encoding='utf-8')
    assert er.main(['--exports', str(tmp_path), '--names', str(names),
                    '--out', str(tmp_path / 'o'), '--suffix', '_L&x']) == 2


# --------------------------------------------- per-part completeness (2026-09-27)

def test_an_fbx_export_interrupted_after_a_part_is_not_done(tmp_path):
    """RealityScan writes each part's .rsInfo as that part finishes, so an
    FBX export killed after part 1 leaves parts 0-1 complete and part 2
    absent. 'At least one file per pattern' called that done."""
    _meshes(tmp_path, 'zone_1_c42_L', parts=3,
            skip={'fbx/zone_1_c42_L_0000002.fbx', 'fbx/zone_1_c42_L_0000002.fbx.rsInfo'})
    assert not er.component_done(str(tmp_path), 'zone_1_c42', 'meshes', '_L')


def test_a_part_without_its_rsinfo_is_not_done(tmp_path):
    _meshes(tmp_path, 'zone_1_c42_L', parts=3,
            skip={'fbx/zone_1_c42_L_0000002.fbx.rsInfo'})
    assert not er.component_done(str(tmp_path), 'zone_1_c42', 'meshes', '_L')


def test_an_obj_part_without_its_mtl_is_not_done(tmp_path):
    _meshes(tmp_path, 'zone_1_c42_L', parts=3,
            skip={'obj/zone_1_c42_L_0000001.mtl'})
    assert not er.component_done(str(tmp_path), 'zone_1_c42', 'meshes', '_L')


def test_a_bracket_in_the_name_is_not_a_glob_class(tmp_path):
    """glob read 'G[1]' as a character class: a finished component stayed
    'to do' until the driver's stall abort."""
    root = tmp_path / 'ex[port]s'
    _meshes(root, 'G[1]_L', parts=2)
    _ply(root, 'G[1]_L')
    assert er.component_done(str(root), 'G[1]', 'meshes', '_L', 'jpg')
    assert er.component_done(str(root), 'G[1]', 'ply', '_L')


def test_cli_textures_jpg_counts_a_png_tree_as_remaining(tmp_path, capsys):
    """The dive driver's retry oracle: without --textures wiring, a PNG
    export would read 'done' and the loop would finish on the wrong tree."""
    exports = tmp_path / 'exports'
    _meshes(exports, 'c1_L', tex='png')
    names = tmp_path / 'all.names'
    names.write_text('c1\n', encoding='utf-8')
    out = tmp_path / 'left.names'
    rc = er.main(['--exports', str(exports), '--names', str(names),
                  '--out', str(out), '--suffix', '_L', '--textures', 'jpg'])
    assert rc == 0 and out.read_bytes() == b'c1\r\n'
    assert 'REMAINING=1' in capsys.readouterr().out.splitlines()


def test_a_list_that_cannot_be_written_leaves_the_old_one_whole(tmp_path):
    """A non-ASCII name used to truncate the list to the names before it;
    the driver would then have exported that prefix as 'the rest'."""
    names = tmp_path / 'all.names'
    names.write_text('A\nzone_é\n', encoding='utf-8')
    out = tmp_path / 'left.names'
    out.write_bytes(b'previous\r\n')
    rc = er.main(['--exports', str(tmp_path / 'exports'), '--names', str(names),
                  '--out', str(out)])
    assert rc == 2
    assert out.read_bytes() == b'previous\r\n'


def test_an_unwritable_list_is_exit_2_not_a_traceback(tmp_path):
    names = tmp_path / 'all.names'
    names.write_text('c1\n', encoding='utf-8')
    rc = er.main(['--exports', str(tmp_path), '--names', str(names),
                  '--out', str(tmp_path / 'no' / 'such' / 'dir' / 'left.names')])
    assert rc == 2
