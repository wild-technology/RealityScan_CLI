#!/usr/bin/env python3
"""ExportRegistrations.bat + modules/export_registrations.py.

The workflow exists to read a project that must NOT change (a v1 baseline
kept for comparison, or an operator's hand-corrected assembly), so the
property that matters most is structural: it never saves. The driver's
census is what turns "exit 0" into "every CSV is present and complete".

No RealityScan is launched (testing rules: test structurally).
"""
from __future__ import annotations

import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO_ROOT)

from modules.export_registrations import census, read_registration_csv  # noqa: E402

BAT = os.path.join(REPO_ROOT, 'modules', 'realityscan_interface', 'RS_CLI',
                   'Scripts', 'ExportRegistrations.bat')


def _text() -> str:
    with open(BAT, encoding='ascii') as fh:
        return fh.read()


def _code_lines() -> list[str]:
    return [ln.strip() for ln in _text().splitlines()
            if ln.strip() and not ln.strip().startswith('::')
            and not ln.strip().lower().startswith('echo ')]


def test_workflow_never_saves():
    """A -save here would rewrite the baseline it was pointed at."""
    assert not any('-save' in ln for ln in _code_lines())


def test_workflow_quits_without_saving_on_both_exits():
    code = _code_lines()
    quits = [ln for ln in code if ln.endswith('-quit')]
    assert len(quits) == 2          # normal end and :fail


def test_empty_list_refused_before_boot():
    text = _text()
    assert 'if %name_count% EQU 0 goto :emptyList' in text
    assert text.index('goto :emptyList') < text.index('startRealityScan.bat')


def test_each_csv_is_gated_on_its_header():
    text = _text()
    export = text.index('call :run -exportRegistration')
    gate = text.index('findstr.exe /n /r /c:"#cameras [0-9][0-9]*"')
    assert export < gate
    assert re.search(r'(?m)^:registrationFormat\s*$', text)
    assert re.search(r'(?m)^:registrationMissing\s*$', text)


def test_component_is_selected_before_export():
    text = _text()
    assert (text.index('call :run -selectComponent "%comp%"')
            < text.index('call :run -exportRegistration'))


def test_export_deliverables_read_only_mode_skips_the_save():
    """RS_EXPORT_READ_ONLY must jump over BOTH the residual sweep and the
    -save, and land before the per-component exports."""
    path = os.path.join(os.path.dirname(BAT), 'ExportDeliverables.bat')
    with open(path, encoding='ascii') as fh:
        text = fh.read()
    gate = text.index('if defined RS_EXPORT_READ_ONLY goto :skipSweep')
    sweep = text.index('call :try_delete_model %%M')
    save = text.index('call :run -save "%scene_path%"')
    skip = re.search(r'(?m)^:skipSweep\s*$', text).start()
    done = re.search(r'(?m)^:sweepDone\s*$', text).start()
    first_export = text.index('call :export_component')
    assert gate < sweep < save < skip < done < first_export
    # the only -save in the file is the one the gate jumps over
    assert text.count('call :run -save') == 1


def _csv(path, header, rows):
    with open(path, 'w', encoding='utf-8') as fh:
        if header is not None:
            fh.write(header + '\n')
        fh.write('#name,x,y,z,yaw,pitch,roll,focal,k1,k2\n')
        for r in rows:
            fh.write(r + '\n')


def test_parse_positions_and_header(tmp_path):
    p = tmp_path / 'Component 7.csv'
    _csv(p, '#cameras 2', ['a.jpg,710829.44,8428118.5,-680.7,1,2,3,16,0,0',
                           'b.jpg,710830.00,8428119.0,-681.0,1,2,3,16,0,0'])
    rec = read_registration_csv(str(p))
    assert rec['declared'] == 2
    assert rec['cameras'][0] == ('a.jpg', 710829.44, 8428118.5, -680.7)


def test_census_flags_missing_short_and_headerless(tmp_path):
    _csv(tmp_path / 'ok.csv', '#cameras 1', ['a.jpg,1,2,3,0,0,0,16,0,0'])
    _csv(tmp_path / 'short.csv', '#cameras 3', ['a.jpg,1,2,3,0,0,0,16,0,0'])
    _csv(tmp_path / 'nohdr.csv', None, ['a.jpg,1,2,3,0,0,0,16,0,0'])
    problems = census(str(tmp_path), ['ok', 'short', 'nohdr', 'absent'])
    joined = ' | '.join(problems)
    assert len(problems) == 3
    assert 'short: header declares 3' in joined
    assert 'nohdr: no "#cameras N" header' in joined
    assert 'absent: no CSV' in joined


def test_export_deliverables_ply_params_override_is_checked():
    """RS_PLY_PARAMS may replace the dense-PLY preset, and a missing file
    must stop the workflow before an instance boots."""
    path = os.path.join(os.path.dirname(BAT), 'ExportDeliverables.bat')
    with open(path, encoding='ascii') as fh:
        text = fh.read()
    override = text.index('set "PlyParams=%RS_PLY_PARAMS%"')
    check = text.index('if not exist "%PlyParams%"')
    assert override < check < text.index('startRealityScan.bat')


def test_export_deliverables_fbx_skip_is_a_goto_not_a_block():
    """RS_EXPORT_SKIP_FBX jumps over the FBX export; the FBX :run keeps its
    `|| exit /b 1` at top level, never inside a parenthesised block."""
    path = os.path.join(os.path.dirname(BAT), 'ExportDeliverables.bat')
    with open(path, encoding='ascii') as fh:
        text = fh.read()
    gate = text.index('if defined RS_EXPORT_SKIP_FBX goto :skipFbx')
    fbx = text.index(r'"%out_dir%\%comp%\fbx\%comp%.fbx"')
    skip = re.search(r'(?m)^:skipFbx\s*$', text).start()
    done = re.search(r'(?m)^:fbxDone\s*$', text).start()
    assert gate < fbx < skip < done
    fbx_line = [ln for ln in text.splitlines()
                if r'\fbx\%comp%.fbx"' in ln][0]
    assert fbx_line.startswith('call :run')


def test_expected_kinds_honours_both_skips(monkeypatch):
    from modules.export_deliverables import expected_kinds
    monkeypatch.delenv('RS_EXPORT_SKIP_PLY', raising=False)
    monkeypatch.delenv('RS_EXPORT_SKIP_FBX', raising=False)
    assert expected_kinds() == ('obj', 'fbx', 'ply')
    monkeypatch.setenv('RS_EXPORT_SKIP_FBX', '1')
    assert expected_kinds() == ('obj', 'ply')
    monkeypatch.setenv('RS_EXPORT_SKIP_PLY', '1')
    assert expected_kinds() == ('obj',)
