#!/usr/bin/env python3
"""ExportDeliverables.bat, RUN against a stub RealityScan - what it delegates.

WHY THIS EXISTS. The structural tests (test_export_suffix_and_modes.py) pin
strings and their order; a mutation review (2026-09-27) showed 8 of 13
inverted .bat branches surviving the full suite that way - a hostile suffix
accepted, jpg silently exported as PNG, a PLY-only pass exporting nothing.
The backward-compatibility proof (no switch set = the historical command
sequence) existed only in the NA165 research folder. Here the workflow's own
control flow runs, and the delegated command stream is the assertion.

HOW, and why it cannot reach RealityScan (CLAUDE.md hard rule 1,
.claude/rules/testing.md):
  - the .bat is COPIED into tmp_path beside a stub SetVariables.bat and a
    stub startRealityScan.bat that records "BOOT" and exits. The stub
    SetVariables makes %RealityScan% `call` a stub .cmd: a -waitCompleted is
    only logged, and every -delegateTo runs this interpreter on a stub
    script that records the argv and plays RealityScan's part (below).
    Calling a batch instead of an exe saves two process start-ups in three,
    in a file whose whole cost is process start-up; the workflow sees the
    same arguments and the same exit codes;
  - the copy's `ping -n N 127.0.0.1 >nul` grace pauses are replaced with
    `rem` - the stub completes synchronously, so they only cost seconds.
    Nothing else in the copy is touched, and the test checks that;
  - the stub writes errors_<inst>.txt on request, exactly where ErrorWriter
    would, so :run, :run_geoimport and :try_delete_model take their real
    branches; -exportRegistration writes a CSV in the chosen format.

Windows only (cmd.exe semantics are the subject).

Run:  python -m pytest testing/test_export_deliverables_stub.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='cmd.exe workflow')

REPO_ROOT = Path(__file__).resolve().parents[1]
RS_CLI = REPO_ROOT / 'modules' / 'realityscan_interface' / 'RS_CLI'
PRESETS = ('ModelExportParamsOBJ_NiraParts.xml', 'ModelExportParamsFBX_Parts.xml',
           'ModelExportParamsOBJ_NiraParts_JPG.xml', 'ModelExportParamsFBX_Parts_JPG.xml',
           'ModelExportParamsPLY_DensePoints.xml', 'RegistrationExportParams_Poses.xml')
INSTANCE = 'RSSTUB'
PING = re.compile(rb'(?m)^([ \t]*)ping -n \d 127\.0\.0\.1 >nul\r$')

STUB_RS = r'''
import json, os, sys
args = sys.argv[1:]
with open(os.environ['STUB_CALLS'], 'a', encoding='utf-8') as fh:
    fh.write('\x1f'.join(args) + '\n')
cmd = args[2:]
line = ' '.join(cmd)
errors = os.path.join(os.environ['ErrorPath'], 'errors_%s.txt' % args[1])
for needle, text in json.loads(os.environ.get('STUB_ERRORS_ON', '{}')).items():
    if needle in line:
        with open(errors, 'a', encoding='utf-8') as fh:
            fh.write(text + '\n')
        sys.exit(0)
if cmd[0] == '-exportRegistration':
    body = {'poses': '#cameras 2\n#name,lat,lon,alt,x,y,z\na.jpg,1,2,3,4,5,6\n'
                     'b.jpg,1,2,3,4,5,6\n',
            'membership': '#cameras 2\n#name\na.jpg\nb.jpg\n'}.get(
        os.environ.get('STUB_REGISTRATION', 'poses'))
    if body is not None:
        with open(cmd[1], 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(body)
elif cmd[0] == '-exportModel':
    os.makedirs(os.path.dirname(cmd[2]), exist_ok=True)
    with open(cmd[2], 'wb') as fh:
        fh.write(b'x')
'''


def _write_bat(path: Path, lines) -> None:
    """CRLF - LF intermittently breaks cmd's label search (test_attach_mode)."""
    with open(path, 'w', encoding='ascii', newline='\r\n') as fh:
        fh.write('\n'.join(lines) + '\n')


class Workflow:
    """One hermetic copy of ExportDeliverables.bat and its stubs."""

    def __init__(self, root: Path, names=('c0',)):
        self.root = root
        self.scripts = root / 'RS_CLI' / 'Scripts'
        self.meta = root / 'RS_CLI' / 'Metadata'
        self.errors = root / 'RS_CLI' / 'Errors'
        for d in (self.scripts, self.meta, self.errors):
            d.mkdir(parents=True)
        for name in PRESETS:
            shutil.copy2(RS_CLI / 'Metadata' / name, self.meta / name)
        source = (RS_CLI / 'Scripts' / 'ExportDeliverables.bat').read_bytes()
        copy, n = PING.subn(rb'\1rem grace pause elided by the test\r', source)
        assert n >= 6, 'the :run / :try_delete_model grace pauses moved'
        assert not re.search(rb'(?im)^[ \t]*ping\b', copy), 'an unelided ping'
        self.bat = self.scripts / 'ExportDeliverables.bat'
        self.bat.write_bytes(copy)
        stub = root / 'stub_rs.py'
        stub.write_text(STUB_RS, encoding='utf-8')
        stub_cmd = root / 'stub_rs.cmd'
        _write_bat(stub_cmd, [
            '@echo off',
            'if /i "%~1" == "-delegateTo" goto :delegate',
            '>>"%STUB_CALLS%" echo %*',
            'exit /b 0',
            ':delegate',
            f'"{sys.executable}" -I -S "{stub}" %*',
            'exit /b %errorlevel%',
        ])
        self.calls = root / 'calls.log'
        _write_bat(self.scripts / 'SetVariables.bat', [
            '@echo off',
            f'set RealityScan=call "{stub_cmd}"',
            f'if not defined RS_INSTANCE set RS_INSTANCE={INSTANCE}',
            f'set "Metadata={self.meta}"',
            f'set "ErrorPath={self.errors}"',
        ])
        _write_bat(self.scripts / 'startRealityScan.bat', [
            '@echo off',
            '>>"%STUB_CALLS%" echo BOOT',
            'exit /b 0',
        ])
        self.project = root / 'Assembly.rsproj'
        self.project.write_bytes(b'<RealityScan/>')
        self.names = root / 'components.names'
        self.names.write_bytes(b''.join(n.encode() + b'\r\n' for n in names))
        self.exports = root / 'exports'

    @property
    def errors_file(self) -> Path:
        return self.errors / f'errors_{INSTANCE}.txt'

    def run(self, switches=None, errors_on=None, registration='poses'):
        env = {k: v for k, v in os.environ.items()
               if not k.upper().startswith(('RS_', 'STUB_'))
               and k.upper() not in ('REALITYSCAN', 'METADATA', 'ERRORPATH')}
        env.update({'RS_INSTANCE': INSTANCE, 'STUB_CALLS': str(self.calls),
                    'STUB_ERRORS_ON': json.dumps(errors_on or {}),
                    'STUB_REGISTRATION': registration})
        env.update(switches or {})
        proc = subprocess.run(
            [str(self.bat), str(self.project), str(self.exports), str(self.names)],
            cwd=str(self.scripts), env=env, capture_output=True, text=True,
            stdin=subprocess.DEVNULL, timeout=300)
        lines = self.calls.read_text(encoding='utf-8').splitlines() \
            if self.calls.is_file() else []
        # stub_rs.py joins a delegated argv with \x1f; the .cmd logs the
        # rest (-waitCompleted <inst>, BOOT) as typed.
        calls = [l.split('\x1f') if '\x1f' in l else l.split() for l in lines]
        return Result(proc, calls)


class Result:
    def __init__(self, proc, calls):
        self.rc = proc.returncode
        self.out = proc.stdout
        self.calls = calls
        # Every delegated command, in order, without its -delegateTo <inst>.
        self.delegated = [c[2:] for c in calls if c[:1] == ['-delegateTo']]
        self.waits = [c for c in calls if c[:1] == ['-waitCompleted']]
        self.booted = ['BOOT'] in calls

    def ops(self):
        return [d[0] for d in self.delegated]

    def index(self, op, *args):
        return self.delegated.index([op, *args])


@pytest.fixture
def wf(tmp_path):
    return Workflow(tmp_path)


def _model_exports(wf, stem, comp, obj_preset, fbx_preset):
    ex = str(wf.exports)
    return [
        ['-selectComponent', comp],
        ['-exportModel', f'{comp}_Simplified_Textured',
         f'{ex}\\{stem}\\obj\\{stem}.obj', str(wf.meta / obj_preset)],
        ['-exportModel', f'{comp}_Simplified_Textured',
         f'{ex}\\{stem}\\fbx\\{stem}.fbx', str(wf.meta / fbx_preset)],
        ['-selectModel', f'{comp}_HighPoly_Raw'],
        ['-calculateVertexColors'],
        ['-exportModel', f'{comp}_HighPoly_Raw', f'{ex}\\{stem}\\ply\\{stem}_dense.ply',
         str(wf.meta / 'ModelExportParamsPLY_DensePoints.xml')],
    ]


# ------------------------------------------------------ the default stream

def test_no_switch_set_is_the_historical_stream(tmp_path):
    """Byte for byte what the pre-switch file delegated (verified against
    git HEAD's ExportDeliverables.bat with this harness, 2026-09-27)."""
    wf = Workflow(tmp_path, ('c0', 'c1'))
    r = wf.run(errors_on={'-selectModel Model ': 'result code 2147942487'})
    assert r.rc == 0, r.out
    expected = [['-load', str(wf.project)]]
    expected += [['-selectModel', f'Model {i}'] for i in range(1, 10)]
    expected += [['-save', str(wf.project)]]
    for comp in ('c0', 'c1'):
        expected += _model_exports(wf, comp, comp, 'ModelExportParamsOBJ_NiraParts.xml',
                                   'ModelExportParamsFBX_Parts.xml')
    expected += [['-quit']]
    assert r.calls[0] == ['BOOT']
    assert r.delegated == expected
    assert len(r.waits) == 2 * (len(expected) - 1)     # every op but -quit
    # the nine absent residuals were MOVED to evidence, never deleted
    assert len(list(wf.errors.glob(f'expected_select_{INSTANCE}_Model_*.txt'))) == 9
    assert not wf.errors_file.exists()


def test_suffix_jpg_and_no_save_rename_and_repoint_only(wf):
    r = wf.run({'RS_EXPORT_SUFFIX': '_L', 'RS_EXPORT_TEXTURES': 'JPG',
                'RS_EXPORT_NO_SAVE': '0', 'RS_PROJECT_CRS': 'epsg:32702'})
    assert r.rc == 0, r.out
    expected = [['-load', str(wf.project)],
                ['-setOutputCoordinateSystem', 'epsg:32702'],
                ['-setProjectCoordinateSystem', 'epsg:32702'],
                ['-setOutputCoordinateSystem', 'epsg:32702']]
    for comp in ('c0',):
        expected += _model_exports(wf, comp + '_L', comp,
                                   'ModelExportParamsOBJ_NiraParts_JPG.xml',
                                   'ModelExportParamsFBX_Parts_JPG.xml')
    expected += [['-quit']]
    assert r.delegated == expected          # NO_SAVE=0 still means no save
    assert sorted(p.name for p in wf.exports.iterdir()) == ['c0_L']


def test_a_lower_case_switch_name_is_honoured(wf):
    """cmd looks names up case-insensitively; the validator must too."""
    r = wf.run({'rs_export_suffix': '_L', 'RS_EXPORT_NO_SAVE': '1',
                'RS_EXPORT_SKIP_PLY': '1'})
    assert r.rc == 0, r.out
    assert ['-exportModel', 'c0_Simplified_Textured',
            f'{wf.exports}\\c0_L\\obj\\c0_L.obj',
            str(wf.meta / 'ModelExportParamsOBJ_NiraParts.xml')] in r.delegated


def test_ply_only_exports_only_the_dense_ply(wf):
    r = wf.run({'RS_EXPORT_ONLY_PLY': '1', 'RS_EXPORT_NO_SAVE': '1'})
    assert r.rc == 0, r.out
    assert not [d for d in r.delegated if 'Simplified' in ' '.join(d)]
    plys = [d for d in r.delegated if d[0] == '-exportModel']
    assert [d[1] for d in plys] == ['c0_HighPoly_Raw']
    assert sorted(p.name for p in (wf.exports / 'c0').iterdir()) == ['ply']


def test_skip_ply_exports_meshes_and_makes_no_ply_folder(wf):
    r = wf.run({'RS_EXPORT_SKIP_PLY': '1', 'RS_EXPORT_NO_SAVE': '1'})
    assert r.rc == 0, r.out
    assert '-calculateVertexColors' not in r.ops()
    assert sorted(p.name for p in (wf.exports / 'c0').iterdir()) == ['fbx', 'obj']


# ----------------------------------------------- exact-target georegistration

def _target_files(wf):
    log = wf.root / 'flight_log_target_2L_UTM.txt'
    log.write_text('Name;X;Y;Alt\n', encoding='utf-8')
    params = wf.root / 'FlightLogParams_2L.xml'
    params.write_text('<Configuration/>\n', encoding='utf-8')
    return str(log), str(params)


def test_target_log_import_and_update_sit_between_the_crs_pin_and_the_exports(wf):
    log, params = _target_files(wf)
    r = wf.run({'RS_EXPORT_TARGET_LOG': log, 'RS_EXPORT_TARGET_PARAMS': params,
                'RS_PROJECT_CRS': 'epsg:32702', 'RS_EXPORT_SUFFIX': '_L',
                'RS_EXPORT_SKIP_PLY': '1'})
    assert r.rc == 0, r.out
    ops = r.ops()
    imp = r.index('-importFlightLog', log, params)
    assert ops[imp + 1] == '-update'
    last_pin = max(i for i, o in enumerate(ops) if o.endswith('CoordinateSystem'))
    assert last_pin < imp
    assert ops.index('-save') < imp, 'the moved state must never be saved'
    assert imp + 1 < ops.index('-exportModel')
    assert ops.count('-update') == 1 and ops.count('-importFlightLog') == 1


def test_the_documented_import_warning_is_tolerated_and_kept(wf):
    log, params = _target_files(wf)
    r = wf.run({'RS_EXPORT_TARGET_LOG': log, 'RS_EXPORT_TARGET_PARAMS': params,
                'RS_EXPORT_NO_SAVE': '1'},
               errors_on={'-importFlightLog': 'process 7 result code 2181038335'})
    assert r.rc == 0, r.out
    assert '-update' in r.ops() and '-exportModel' in r.ops()
    moved = wf.errors / f'expected_18002_{INSTANCE}.txt'
    assert '2181038335' in moved.read_text(encoding='utf-8')
    assert not wf.errors_file.exists()


def test_any_other_import_failure_stops_before_update_and_export(wf):
    log, params = _target_files(wf)
    r = wf.run({'RS_EXPORT_TARGET_LOG': log, 'RS_EXPORT_TARGET_PARAMS': params,
                'RS_EXPORT_NO_SAVE': '1'},
               errors_on={'-importFlightLog': 'process 7 result code 2147942487'})
    assert r.rc == 1
    assert '-update' not in r.ops() and '-exportModel' not in r.ops()
    assert r.ops()[-1] == '-quit'
    assert wf.errors_file.exists()          # evidence left for the caller


# ------------------------------------------------------------ camera poses

def test_registration_writes_one_poses_csv_per_listed_component(tmp_path):
    wf = Workflow(tmp_path, ('c0', 'c1'))
    log, params = _target_files(wf)
    poses = wf.root / 'poses' / 'after'           # created by the workflow
    r = wf.run({'RS_EXPORT_REGISTRATION_DIR': str(poses),
                'RS_EXPORT_TARGET_LOG': log, 'RS_EXPORT_TARGET_PARAMS': params,
                'RS_EXPORT_NO_SAVE': '1', 'RS_EXPORT_SKIP_PLY': '1'})
    assert r.rc == 0, r.out
    assert sorted(p.name for p in poses.iterdir()) == ['c0.csv', 'c1.csv']
    pose_params = str(wf.meta / 'RegistrationExportParams_Poses.xml')
    for comp in ('c0', 'c1'):
        i = r.index('-exportRegistration', str(poses / f'{comp}.csv'), pose_params)
        assert r.delegated[i - 2:i] == [['-selectComponent', comp],
                                        ['-deselectAllImages']]
        assert r.index('-update') < i < r.ops().index('-exportModel')
    assert r.ops().count('-exportRegistration') == 2


@pytest.mark.parametrize('written', ['membership', 'none'])
def test_a_wrong_or_missing_poses_csv_is_fatal(wf, written):
    """An unresolved format id falls back silently; the call has also
    returned 0 without writing anything. Only the content is proof."""
    r = wf.run({'RS_EXPORT_REGISTRATION_DIR': str(wf.root / 'poses'),
                'RS_EXPORT_NO_SAVE': '1'}, registration=written)
    assert r.rc == 1
    assert '-exportModel' not in r.ops()
    assert r.ops().count('-exportRegistration') == 1
    assert r.ops()[-1] == '-quit'


# ------------------------------------------------ refused before any boot

def _refusals(wf):
    log, params = _target_files(wf)
    clash = wf.root / 'clash'
    clash.mkdir()
    (clash / 'c0.csv').write_text('#cameras 1\n', encoding='utf-8')
    inj = 'type nul>INJECTED'
    return {
        'suffix_amp': {'RS_EXPORT_SUFFIX': '_L&' + inj},
        'suffix_lower_name': {'rs_export_suffix': '_L&' + inj},
        'suffix_mixed_name': {'Rs_Export_Suffix': '_L&' + inj},
        'suffix_cr': {'RS_EXPORT_SUFFIX': '_L\r&' + inj},
        'suffix_lf': {'RS_EXPORT_SUFFIX': '_L\n&' + inj},
        'suffix_quote': {'RS_EXPORT_SUFFIX': '_L"&' + inj + '&rem "'},
        'suffix_bang': {'RS_EXPORT_SUFFIX': '_L!PATH!'},
        'suffix_percent': {'RS_EXPORT_SUFFIX': '_L%PATH%'},
        'suffix_dot': {'RS_EXPORT_SUFFIX': '_L.v2'},
        'textures_jpeg': {'RS_EXPORT_TEXTURES': 'jpeg'},
        'textures_amp': {'RS_EXPORT_TEXTURES': 'jpg&' + inj},
        'textures_cr': {'RS_EXPORT_TEXTURES': 'jpg\r&' + inj},
        'both_ply_modes': {'RS_EXPORT_SKIP_PLY': '1', 'RS_EXPORT_ONLY_PLY': '1'},
        'target_without_params': {'RS_EXPORT_TARGET_LOG': log},
        'params_without_target': {'RS_EXPORT_TARGET_PARAMS': params},
        'target_missing': {'RS_EXPORT_TARGET_LOG': log + '.absent',
                           'RS_EXPORT_TARGET_PARAMS': params},
        'target_quote': {'RS_EXPORT_TARGET_LOG': log + '"&' + inj + '&rem "',
                         'RS_EXPORT_TARGET_PARAMS': params},
        'target_percent': {'RS_EXPORT_TARGET_LOG': log + '%PATH%',
                           'RS_EXPORT_TARGET_PARAMS': params},
        'params_paren': {'RS_EXPORT_TARGET_LOG': log,
                         'RS_EXPORT_TARGET_PARAMS': params + ')&' + inj},
        'registration_amp': {'RS_EXPORT_REGISTRATION_DIR': str(wf.root) + '&' + inj},
        'registration_cr': {'RS_EXPORT_REGISTRATION_DIR': str(wf.root) + '\r&' + inj},
        'registration_clash': {'RS_EXPORT_REGISTRATION_DIR': str(clash)},
    }


REFUSALS = ['suffix_amp', 'suffix_lower_name', 'suffix_mixed_name', 'suffix_cr',
            'suffix_lf', 'suffix_quote', 'suffix_bang', 'suffix_percent',
            'suffix_dot', 'textures_jpeg', 'textures_amp', 'textures_cr',
            'both_ply_modes', 'target_without_params', 'params_without_target',
            'target_missing', 'target_quote', 'target_percent', 'params_paren',
            'registration_amp', 'registration_cr', 'registration_clash']


@pytest.mark.parametrize('case', REFUSALS)
def test_a_bad_value_is_refused_before_boot_and_never_run(wf, case):
    switches = _refusals(wf)[case]
    r = wf.run(switches)
    assert r.rc == 1, r.out
    assert r.calls == [], 'refused AFTER booting (or calling) RealityScan'
    injected = [p for p in wf.root.rglob('INJECTED*')]
    assert injected == [], f'the value was executed: {injected}'
    assert not wf.exports.exists()
    if case == 'registration_clash':
        assert (wf.root / 'clash' / 'c0.csv').read_text(encoding='utf-8') == '#cameras 1\n'


@pytest.mark.parametrize('preset, switches', [
    ('ModelExportParamsOBJ_NiraParts.xml', {}),
    ('ModelExportParamsFBX_Parts_JPG.xml', {'RS_EXPORT_TEXTURES': 'jpg'}),
    ('ModelExportParamsPLY_DensePoints.xml', {}),
    ('RegistrationExportParams_Poses.xml', {'RS_EXPORT_REGISTRATION_DIR': 'POSES'}),
])
def test_a_missing_preset_is_refused_before_boot(wf, preset, switches):
    """Never export with RealityScan's defaults: a missing params file is a
    stop before the (up to 45 min) project load, not an export in PNG, in
    the wrong frame or in the membership format."""
    (wf.meta / preset).unlink()
    switches = {k: (str(wf.root / 'poses') if v == 'POSES' else v)
                for k, v in switches.items()}
    r = wf.run(dict(switches, RS_EXPORT_NO_SAVE='1'))
    assert r.rc == 1 and r.calls == []


def test_a_stale_errors_file_is_refused_before_boot(wf):
    wf.errors_file.write_text('left over\n', encoding='utf-8')
    r = wf.run({'RS_EXPORT_NO_SAVE': '1'})
    assert r.rc == 1 and r.calls == []
    assert wf.errors_file.read_text(encoding='utf-8') == 'left over\n'


def test_the_refusal_labels_all_exist(wf):
    """A new switch must not goto a label that is not there (cmd would print
    'The system cannot find the batch label' and carry on as rc 1 - an
    accident that passes the refusal tests for the wrong reason)."""
    text = wf.bat.read_text(encoding='ascii')
    jumps = set(re.findall(r'goto (:\w+)', text))
    labels = set(re.findall(r'(?m)^(:\w+)\s*$', text))
    assert jumps <= labels, jumps - labels
