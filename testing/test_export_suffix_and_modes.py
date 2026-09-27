#!/usr/bin/env python3
"""Re-export under a new name, from a project that must not be written.

WHY THIS EXISTS. NA165/H2060 (2026-09-26) had to re-export its 39 delivered
components with every file stem carrying `_L` and JPG textures, from the
delivered assembly - which must never be saved again (it is the thing the
deliverables were exported from, and the dated snapshot of it is off-box).
ExportDeliverables.bat could do none of that:

  - the stem came from `%comp%`, and `%comp%` also SELECTED the component
    and its models, so renaming the output meant renaming (re-modelling) the
    component: ~40 machine-hours for a filename;
  - it always swept residuals and `-save`d the project before exporting;
  - its OBJ/FBX presets hard-code PNG, and other dives still want PNG;
  - a PLY-only pass was not expressible (only RS_EXPORT_SKIP_PLY existed).

The fix separates what is SELECTED (existing names) from what is WRITTEN
(`<comp><RS_EXPORT_SUFFIX>`), and adds RS_EXPORT_NO_SAVE / RS_EXPORT_TEXTURES /
RS_EXPORT_ONLY_PLY. Every switch is checked before an instance boots.

Structural, like test_cmd_boundary_guards: no script is executed - they are
all boot-capable. The behaviour itself - the delegated command stream, each
refusal, the exact-target import and the poses export - is run against a
stub RealityScan in test_export_deliverables_stub.py.

Run:  python -m pytest testing/test_export_suffix_and_modes.py
"""
from __future__ import annotations

import os
import re
import sys
import xml.etree.ElementTree as ET

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO_ROOT)

from modules import export_deliverables as ed  # noqa: E402

RS_CLI = os.path.join(REPO_ROOT, 'modules', 'realityscan_interface', 'RS_CLI')
SCRIPTS = os.path.join(RS_CLI, 'Scripts')
META = os.path.join(RS_CLI, 'Metadata')

SWITCHES = ('RS_EXPORT_SUFFIX', 'RS_EXPORT_TEXTURES', 'RS_EXPORT_NO_SAVE',
            'RS_EXPORT_SKIP_PLY', 'RS_EXPORT_ONLY_PLY')


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    # setenv first so monkeypatch RECORDS the original (usually unset) value:
    # apply_switches() writes os.environ directly, and a bare delenv of an
    # absent key records nothing - the switches then leaked into every later
    # test in the process (6 export-driver tests failed that way).
    for key in SWITCHES:
        monkeypatch.setenv(key, 'x')
        monkeypatch.delenv(key)


def _bat() -> str:
    with open(os.path.join(SCRIPTS, 'ExportDeliverables.bat'),
              encoding='utf-8', newline='') as f:
        return f.read()


def _code_lines(text):
    """Non-comment lines (comments name commands; assertions must not)."""
    return [l for l in text.splitlines() if not l.lstrip().startswith('::')]


def _preset(name):
    root = ET.parse(os.path.join(META, name + '.xml')).getroot()
    return {e.attrib['key']: e.attrib['value'] for e in root.findall('entry')}


# ------------------------------------------------ selected vs written names

def test_delayed_expansion_is_disabled_not_inherited():
    """A plain setlocal inherits the caller's state: from a driver with
    EnableDelayedExpansion, D:\\dive\\bang!x!\\exports arrived as
    D:\\dive\\banginherited\\exports (measured). The header claimed the
    opposite."""
    first = next(l for l in _code_lines(_bat()) if l.strip().lower().startswith('setlocal'))
    assert first.strip() == 'setlocal DisableDelayedExpansion'


def test_the_component_is_selected_by_its_existing_name():
    text = _bat()
    assert 'set "comp=%~1"' in text
    assert 'call :run -selectComponent "%comp%"' in text
    assert '-exportModel "%comp%_Simplified_Textured"' in text
    assert '-selectModel "%comp%_HighPoly_Raw"' in text
    assert '-exportModel "%comp%_HighPoly_Raw"' in text


def test_every_output_path_uses_the_suffixed_stem():
    text = _bat()
    assert 'set "stem=%~1%RS_EXPORT_SUFFIX%"' in text
    exports = [l for l in _code_lines(text) if '-exportModel' in l]
    assert len(exports) == 3, exports
    assert any('"%out_dir%\\%stem%\\obj\\%stem%.obj"' in l for l in exports)
    assert any('"%out_dir%\\%stem%\\fbx\\%stem%.fbx"' in l for l in exports)
    assert any('"%out_dir%\\%stem%\\ply\\%stem%_dense.ply"' in l for l in exports)
    for line in exports:
        assert '\\%comp%' not in line, f'output path still built from %comp%: {line}'


def test_no_dead_highpoly_textured_export_remains():
    """Lines after `exit /b 0` and a stray `)` exported _HighPoly_Textured and
    were unreachable - a trap for the next reader."""
    assert '_HighPoly_Textured' not in '\n'.join(_code_lines(_bat()))


# --------------------------------------------------- switches before boot

def test_every_switch_is_checked_before_an_instance_boots():
    text = _bat()
    boot = text.index('call "%~dp0startRealityScan.bat"')
    for jump in ('goto :conflictingModes', 'goto :badSuffix',
                 'goto :badTextures', 'goto :missingPreset', 'goto :staleErrors',
                 'goto :targetPairing', 'goto :badTargetPath',
                 'goto :missingTarget', 'goto :badRegistrationDir',
                 'goto :missingPoseParams', 'goto :registrationExists'):
        assert text.index(jump) < boot, jump
        label = jump.split()[-1]
        assert len(re.findall(r'(?m)^%s\s*$' % re.escape(label), text)) == 1, label


EXPANDED_SWITCHES = ('RS_EXPORT_SUFFIX', 'RS_EXPORT_TEXTURES', 'RS_EXPORT_TARGET_LOG',
                     'RS_EXPORT_TARGET_PARAMS', 'RS_EXPORT_REGISTRATION_DIR')


@pytest.mark.parametrize('name', EXPANDED_SWITCHES)
def test_no_switch_is_expanded_before_it_is_validated(name):
    """`if "%RS_EXPORT_SUFFIX%"...` would run _L"&cmd while parsing the
    check itself. Every switch that reaches a command line is judged by
    :charsOk first, and nothing expands it with %...% before that call."""
    code = '\n'.join(_code_lines(_bat()))
    check = code.index('call :charsOk %s ' % name)
    assert code.index('%' + name + '%') > check, name


def test_values_are_judged_by_delayed_expansion_not_a_findstr_pipe():
    """`set NAME|findstr ...` was bypassed twice (bat-review 2026-09-27): no /i
    on the name filter let rs_export_suffix through, and findstr /x accepted a
    value with an embedded CR - both ran the payload at the first echo.
    :charsOk reads the value as !%~1!, which cmd never re-parses."""
    code = _code_lines(_bat())
    assert not [l for l in code if re.match(r'\s*set RS_EXPORT_\w*\s*\|', l)]
    assert 'set "rest=!%~1!"' in code
    assert code.count('setlocal EnableDelayedExpansion') == 1


def test_the_whitelists_are_explicit():
    """Case-insensitive substitution removes a-z with A-Z; anything the lists
    do not name - including a CR, LF, tab or non-ASCII - is left and refuses
    the value. Paths add space and . \\ : ' + # @ $ { } [ ] only."""
    text = _bat()
    assert ('for %%C in (A B C D E F G H I J K L M N O P Q R S T U V W X Y Z '
            '0 1 2 3 4 5 6 7 8 9 _ -) do if defined rest set "rest=!rest:%%C=!"'
            in text)
    assert ("for %%C in (. \\ : ' + # @ $ { } [ ]) do if defined rest "
            'set "rest=!rest:%%C=!"' in text)
    assert 'if defined rest set "rest=!rest: =!"' in text
    assert 'call :charsOk RS_EXPORT_SUFFIX stem' in text
    assert 'call :charsOk RS_EXPORT_TEXTURES stem' in text
    for name in ('RS_EXPORT_TARGET_LOG', 'RS_EXPORT_TARGET_PARAMS',
                 'RS_EXPORT_REGISTRATION_DIR'):
        assert f'call :charsOk {name} path' in text, name


def test_the_python_path_whitelist_matches_the_bat():
    ok = r"D:\dive\_agent\target log_2L-UTM.txt"
    assert ed.PATH_RE.match(ok) and ed.PATH_RE.match(r"C:\a'b+c#d@e$f{g}h[i]")
    for bad in ('C:\\a(b)', 'C:\\a,b', 'C:\\a;b', 'C:\\a=b', 'C:\\PROGRA~1',
                'C:\\a&b', 'C:\\a%b%', 'C:\\a!b', 'C:\\a"b', 'C:\\a^b',
                'C:\\a\rb', 'C:\\a\nb', 'C:\\a\tb', 'C:\\\u00e9', 'C:/a/b'):
        assert not ed.PATH_RE.match(bad), repr(bad)


def test_both_ply_switches_together_are_refused():
    assert ('if defined RS_EXPORT_SKIP_PLY if defined RS_EXPORT_ONLY_PLY '
            'goto :conflictingModes') in _bat()


def test_ply_only_skips_the_mesh_exports():
    text = _bat()
    jump = text.index('if defined RS_EXPORT_ONLY_PLY goto :export_ply')
    label = re.search(r'(?m)^:export_ply\s*$', text).start()
    obj = text.index('-exportModel "%comp%_Simplified_Textured"')
    assert text.index('call :run -selectComponent "%comp%"') < jump < obj < label


# ------------------------------------------------------------- no save

def test_no_save_skips_both_the_sweep_and_the_save():
    text = _bat()
    jump = text.index('if defined RS_EXPORT_NO_SAVE goto :skipSave')
    sweep = text.index('call :try_delete_model %%M')
    save = text.index('call :run -save "%scene_path%"')
    label = re.search(r'(?m)^:skipSave\s*$', text).start()
    assert jump < sweep < save < label


def test_the_only_save_in_the_workflow_is_the_guarded_one():
    saves = [l for l in _code_lines(_bat())
             if '-save' in l and not l.lstrip().lower().startswith('echo')]
    assert saves == ['call :run -save "%scene_path%" || goto :fail'], saves


# ------------------------------------------------------------- presets

def test_texture_switch_defaults_to_the_png_presets():
    text = _bat()
    assert 'set "tex=png"' in text
    assert 'set "ObjParams=%MetadataDir%\\ModelExportParamsOBJ_NiraParts.xml"' in text
    assert 'set "FbxParams=%MetadataDir%\\ModelExportParamsFBX_Parts.xml"' in text
    assert ('if "%tex%" == "jpg" set "ObjParams=%MetadataDir%\\'
            'ModelExportParamsOBJ_NiraParts_JPG.xml"') in text
    assert ('if "%tex%" == "jpg" set "FbxParams=%MetadataDir%\\'
            'ModelExportParamsFBX_Parts_JPG.xml"') in text


@pytest.mark.parametrize('png', ['ModelExportParamsOBJ_NiraParts',
                                 'ModelExportParamsFBX_Parts'])
def test_png_presets_are_untouched(png):
    """Other dives keep PNG: the JPG work adds presets, it edits none."""
    assert _preset(png)['MvsMeshExportTexImgFormat_Color8_0'] == 'png'


TEXTURE_KEYS = {'MvsMeshExportTexImgFormat_Color8_0',
                'MvsMeshExportTexImgFormat_Normal_0',
                'MvsMeshExportTexPixFormat_Normal_0',
                'MvsMeshExportTexImgFormat'}


@pytest.mark.parametrize('png', ['ModelExportParamsOBJ_NiraParts',
                                 'ModelExportParamsFBX_Parts'])
def test_jpg_preset_differs_from_its_png_twin_only_in_texture_format(png):
    """By parts, CRS type 3, georeferenced, no move/scale, the .rsInfo - all
    of it must be the PNG preset's, or the JPG export is a different
    deliverable, not the same one in a smaller file."""
    a, b = _preset(png), _preset(png + '_JPG')
    changed = {k for k in set(a) | set(b) if a.get(k) != b.get(k)}
    assert changed <= TEXTURE_KEYS, changed - TEXTURE_KEYS
    assert b['MvsMeshExportTexImgFormat_Color8_0'] == 'jpg'
    assert b['MvsMeshExportTexImgFormat_Normal_0'] == 'jpg'


# ----------------------------------------------------- python side

def test_stem_is_component_plus_suffix(monkeypatch):
    assert ed.export_stem('zone_1_c0') == 'zone_1_c0'
    monkeypatch.setenv('RS_EXPORT_SUFFIX', '_L')
    assert ed.export_stem('zone_1_c0') == 'zone_1_c0_L'
    assert ed.export_stem('zone_1_c0', '_unscaled_L') == 'zone_1_c0_unscaled_L'


@pytest.mark.parametrize('bad', ['_L&x', '_L"', '_L x', '_L.v2', '_L%P%', '_L!'])
def test_a_hostile_suffix_is_refused(monkeypatch, bad):
    monkeypatch.setenv('RS_EXPORT_SUFFIX', bad)
    with pytest.raises(ValueError, match='only letters'):
        ed.export_suffix()


def test_census_looks_in_the_suffixed_folders(tmp_path, monkeypatch):
    """Checking the bare name after a suffixed export reports all missing."""
    monkeypatch.setenv('RS_EXPORT_SUFFIX', '_L')
    for kind in ed.EXPORT_KINDS:
        d = tmp_path / 'c1_L' / kind
        d.mkdir(parents=True)
        (d / f'c1_L_0000000.{kind}').write_text('x', encoding='utf-8')
    assert ed.missing_exports(str(tmp_path), ['c1']) == []
    assert ed.missing_exports(str(tmp_path), ['c1'], suffix='') == [
        'c1/obj', 'c1/fbx', 'c1/ply']


def test_ply_only_expects_only_ply(monkeypatch):
    monkeypatch.setenv('RS_EXPORT_ONLY_PLY', '1')
    assert ed.expected_kinds() == ('ply',)


def test_both_ply_switches_are_refused_in_python_too(monkeypatch):
    monkeypatch.setenv('RS_EXPORT_SKIP_PLY', '1')
    monkeypatch.setenv('RS_EXPORT_ONLY_PLY', '1')
    with pytest.raises(ValueError, match='exports nothing'):
        ed.expected_kinds()


def test_cli_switches_win_over_inherited_ones(monkeypatch):
    monkeypatch.setenv('RS_EXPORT_SKIP_PLY', '1')

    class A:
        suffix, textures, no_save, only = '_L', 'jpg', True, 'ply'
    ed.apply_switches(A)
    assert os.environ['RS_EXPORT_SUFFIX'] == '_L'
    assert os.environ['RS_EXPORT_TEXTURES'] == 'jpg'
    assert os.environ['RS_EXPORT_NO_SAVE'] == '1'
    assert 'RS_EXPORT_SKIP_PLY' not in os.environ
    assert ed.expected_kinds() == ('ply',)


def test_names_the_bat_would_reparse_are_refused():
    assert ed.unsafe_component_names(['zone_1_c0', 'a&b', 'c%d%', 'ok_2']) == [
        'a&b', 'c%d%']


def _driver(tmp_path, monkeypatch, argv_extra, produce_ext=None, during_run=None):
    from modules.realityscan_interface.realityscan_cli import WorkflowResult

    class _Store:
        def get(self, *a, **k):
            return None

        def ask(self, *a, **k):
            return None

    project = tmp_path / 'Assembly.rsproj'
    project.write_bytes(b'p')
    names = tmp_path / 'components.names'
    names.write_text('c0\n', encoding='utf-8')
    exports = tmp_path / 'exports'
    exports.mkdir()
    if produce_ext:
        for kind in ('obj', 'fbx'):
            d = exports / 'c0_L' / kind
            d.mkdir(parents=True)
            (d / f'c0_L_0000000.{kind}').write_bytes(b'x')
            (d / f'c0_L_u1_v1_diffuse.{produce_ext}').write_bytes(
                b'\xff\xd8\xff\xe0' if produce_ext == 'jpg' else b'\x89PNG')
        (exports / 'c0_L' / 'obj' / 'c0_L_0000000.mtl').write_text(
            f'map_Kd c0_L_u1_v1_diffuse.{produce_ext}\n', encoding='utf-8')
    calls = []

    def fake_run(*a, **k):
        calls.append((a, dict(os.environ)))
        if during_run:
            during_run()
        return WorkflowResult(True, 0, 'log.txt', '', [], 1.0)
    monkeypatch.setattr(ed, 'run_export', fake_run)
    monkeypatch.setattr(ed, 'SettingsStore', lambda *a, **k: _Store())
    monkeypatch.setenv('RS_INSTANCE', 'RSTEST')
    monkeypatch.setenv('RS_CACHE_DIR', str(tmp_path))
    monkeypatch.setattr(sys, 'argv', ['export_deliverables.py', '--project',
                                      str(project), '--exports', str(exports),
                                      '--names', str(names)] + argv_extra)
    return ed.main(), calls


def test_driver_refuses_a_bad_suffix_before_running(tmp_path, monkeypatch):
    rc, calls = _driver(tmp_path, monkeypatch, ['--suffix', '_L&x'])
    assert rc == 1 and not calls


def test_driver_passes_the_switches_to_the_workflow(tmp_path, monkeypatch):
    rc, calls = _driver(tmp_path, monkeypatch,
                        ['--suffix', '_L', '--textures', 'jpg', '--no-save',
                         '--only', 'meshes'], produce_ext='jpg')
    assert rc == 0
    env = calls[0][1]
    assert env['RS_EXPORT_SUFFIX'] == '_L'
    assert env['RS_EXPORT_TEXTURES'] == 'jpg'
    assert env['RS_EXPORT_NO_SAVE'] == '1'
    assert env['RS_EXPORT_SKIP_PLY'] == '1'


def test_driver_fails_a_jpg_run_that_wrote_png(tmp_path, monkeypatch):
    """A preset key RealityScan does not honour is silent: success, PNG."""
    rc, _ = _driver(tmp_path, monkeypatch,
                    ['--suffix', '_L', '--textures', 'jpg', '--only', 'meshes'],
                    produce_ext='png')
    assert rc == 1


# ------------------------------------------------ driver edges (review 2026-09-27)

def test_only_all_clears_inherited_ply_switches(tmp_path, monkeypatch):
    monkeypatch.setenv('RS_EXPORT_ONLY_PLY', '1')
    _, calls = _driver(tmp_path, monkeypatch, ['--only', 'all'])
    env = calls[0][1]
    assert 'RS_EXPORT_ONLY_PLY' not in env and 'RS_EXPORT_SKIP_PLY' not in env


def test_an_inherited_bad_texture_value_is_refused_before_running(tmp_path, monkeypatch):
    monkeypatch.setenv('RS_EXPORT_TEXTURES', 'webp')
    rc, calls = _driver(tmp_path, monkeypatch, [])
    assert rc == 1 and not calls


def test_a_name_the_bat_would_reparse_stops_the_driver(tmp_path, monkeypatch):
    monkeypatch.setattr(ed, 'read_component_names', lambda path: ['c0', 'a&b'])
    rc, calls = _driver(tmp_path, monkeypatch, [])
    assert rc == 1 and not calls


def test_save_clears_an_inherited_no_save(tmp_path, monkeypatch):
    monkeypatch.setenv('RS_EXPORT_NO_SAVE', '1')
    _, calls = _driver(tmp_path, monkeypatch, ['--save'])
    assert 'RS_EXPORT_NO_SAVE' not in calls[0][1]


def test_a_suffix_with_a_trailing_newline_is_refused_in_python(monkeypatch):
    r"""`$` matches before a final newline; the pattern ends in \Z."""
    monkeypatch.setenv('RS_EXPORT_SUFFIX', '_L\n')
    with pytest.raises(ValueError, match='only letters'):
        ed.export_suffix()


def test_target_log_needs_its_params(tmp_path, monkeypatch):
    log = tmp_path / 'target.txt'
    log.write_text('x\n', encoding='utf-8')
    rc, calls = _driver(tmp_path, monkeypatch, ['--target-log', str(log)])
    assert rc == 1 and not calls


def test_target_and_registration_switches_reach_the_workflow(tmp_path, monkeypatch):
    log = tmp_path / 'target.txt'
    params = tmp_path / 'params.xml'
    for p in (log, params):
        p.write_text('x\n', encoding='utf-8')
    poses = tmp_path / 'poses'

    def write_poses():
        poses.mkdir()
        (poses / 'c0.csv').write_text('#cameras 2\n#name,lat,lon,alt,x\n',
                                      encoding='utf-8')
    rc, calls = _driver(tmp_path, monkeypatch,
                        ['--suffix', '_L', '--textures', 'jpg', '--only', 'meshes',
                         '--target-log', str(log), '--target-params', str(params),
                         '--registration-dir', str(poses)],
                        produce_ext='jpg', during_run=write_poses)
    assert rc == 0
    env = calls[0][1]
    assert env['RS_EXPORT_TARGET_LOG'] == str(log)
    assert env['RS_EXPORT_TARGET_PARAMS'] == str(params)
    assert env['RS_EXPORT_REGISTRATION_DIR'] == str(poses)


@pytest.mark.parametrize('body', [None, '#cameras 2\n#name\na.jpg\n'])
def test_a_missing_or_wrong_poses_csv_fails_the_census(tmp_path, monkeypatch, body):
    poses = tmp_path / 'poses'

    def write_poses():
        poses.mkdir()
        if body is not None:
            (poses / 'c0.csv').write_text(body, encoding='utf-8')
    rc, _ = _driver(tmp_path, monkeypatch,
                    ['--suffix', '_L', '--textures', 'jpg', '--only', 'meshes',
                     '--registration-dir', str(poses)],
                    produce_ext='jpg', during_run=write_poses)
    assert rc == 1


def test_an_existing_poses_csv_is_refused_before_running(tmp_path, monkeypatch):
    poses = tmp_path / 'poses'
    poses.mkdir()
    (poses / 'c0.csv').write_text('#cameras 1\n', encoding='utf-8')
    rc, calls = _driver(tmp_path, monkeypatch, ['--registration-dir', str(poses)])
    assert rc == 1 and not calls
    assert (poses / 'c0.csv').read_text(encoding='utf-8') == '#cameras 1\n'
