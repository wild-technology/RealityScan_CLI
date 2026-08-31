#!/usr/bin/env python3
"""Silence-is-not-success across the census and the deliverable drivers.

The workspace census is the resume signal for run_models and the WildScan
portal, and it counted the wrong things (audit 2026-08-07):

  - run_models writes models_report.json (both modes); the census read
    only the retired H2024 names, so a fully modelled workspace read
    "pending / no model reports" and the portal re-ticked 'model' on every
    resume - re-booting RealityScan for SaveProjectCopy.bat each time
  - a header-only flight log read 'done | 0 rows'
  - zone folders holding ZERO images read 'done | N zones'
  - export completion was measured against exports/ itself, so a 1-of-6
    export read 'done | 1 component(s) exported'
  - EVALUATION_READY.txt was written BEFORE the assembly result was
    checked, so it could declare a terminal state for a project that was
    never saved
  - a merge report of the wrong SHAPE crashed the census with
    AttributeError (only I/O and JSON errors were guarded)

And no driver ever verified that a deliverable file exists: success was
inferred from exit code plus an errors marker, which the fact base says
RealityScan lies about for do-nothing operations.

Offline: fixture directories only. No RealityScan.

Run:  py -3.13 -m pytest testing/test_census_and_postconditions.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO_ROOT)

import finish_model  # noqa: E402
from modules import export_deliverables  # noqa: E402
from modules.workspace_census import (MODEL_REPORT_NAMES, Workspace,  # noqa: E402
                                      _records)

MERGE_REPORT = {
    'input_scales': {},
    'assembly': {'workflow_success': True},
    'clusters': [{'cluster': 'cluster_0', 'final_components': [
        {'key': 'zone_1/zone_1_c0', 'camera_count': 100},
        {'key': 'zone_2/zone_2_c0', 'camera_count': 90}]}],
}


def _merged(ws, report=None, gate=True):
    merge = ws / 'final_assembly'
    (merge / 'assembly').mkdir(parents=True)
    (merge / 'assembly' / 'Assembly.rsproj').write_bytes(b'p')
    (merge / 'merge_report.json').write_text(
        json.dumps(report if report is not None else MERGE_REPORT),
        encoding='utf-8')
    if gate:
        (merge / 'EVALUATION_READY.txt').write_text('READY', encoding='utf-8')
    return merge


# ------------------------------------------------------------ model census

def test_models_report_json_is_read(tmp_path):
    """The name run_models ACTUALLY writes. A workspace with a valid merge
    report plus exactly that file reported 'pending / no model reports'."""
    ws = tmp_path / 'cruise'
    ws.mkdir()
    _merged(ws)
    (ws / 'models_report.json').write_text(json.dumps({'models': [
        {'component': 'zone_1_c0', 'success': True},
        {'component': 'zone_2_c0', 'success': True}]}), encoding='utf-8')
    status = Workspace(ws).detect()['model']
    assert status.status == 'done', status.summary
    assert all(c.modelled for c in Workspace(ws).components())


def test_the_legacy_report_names_still_census(tmp_path):
    """Old H2024 workspaces must keep working - the new name is ADDED."""
    assert 'models_report.json' in MODEL_REPORT_NAMES
    assert 'final_report.json' in MODEL_REPORT_NAMES
    assert 'fused_models_report.json' in MODEL_REPORT_NAMES
    ws = tmp_path / 'cruise'
    ws.mkdir()
    _merged(ws)
    (ws / 'fused_models_report.json').write_text(json.dumps({'components': [
        {'component': 'zone_1_c0', 'success': True},
        {'component': 'zone_2_c0', 'success': True}]}), encoding='utf-8')
    assert Workspace(ws).detect()['model'].status == 'done'


# ------------------------------------------------------ empty-artifact gates

def test_a_zero_row_flight_log_is_not_done(tmp_path):
    ws = tmp_path / 'cruise'
    (ws / 'raw_images').mkdir(parents=True)
    (ws / 'raw_images' / 'flight_log_53N_UTM.txt').write_text(
        'filename;X (East);Y (North)\n', encoding='utf-8')
    status = Workspace(ws).detect()['georeference']
    assert status.status == 'blocked'
    assert '0 rows' in status.summary


def test_a_log_covering_a_fraction_of_the_imagery_is_partial(tmp_path):
    ws = tmp_path / 'cruise'
    raw = ws / 'raw_images'
    raw.mkdir(parents=True)
    for i in range(10):
        (raw / f'img_{i}.jpg').write_bytes(b'j')
    (raw / 'flight_log_53N_UTM.txt').write_text(
        'filename;X (East);Y (North)\nimg_0.jpg;1;2\n', encoding='utf-8')
    assert Workspace(ws).detect()['georeference'].status == 'partial'


def test_a_full_log_is_done(tmp_path):
    ws = tmp_path / 'cruise'
    raw = ws / 'raw_images'
    raw.mkdir(parents=True)
    for i in range(4):
        (raw / f'img_{i}.jpg').write_bytes(b'j')
    rows = ''.join(f'img_{i}.jpg;1;2\n' for i in range(4))
    (raw / 'flight_log_53N_UTM.txt').write_text(
        'filename;X (East);Y (North)\n' + rows, encoding='utf-8')
    assert Workspace(ws).detect()['georeference'].status == 'done'


def test_image_free_zone_folders_are_not_done(tmp_path):
    """The fingerprint blessed an empty tree for reuse and the census
    called it done - alignment was then handed empty folders."""
    ws = tmp_path / 'cruise'
    batched = ws / 'batched_images_by_zone'
    for zone in ('zone_1', 'zone_2'):
        (batched / zone).mkdir(parents=True)
    (batched / 'batch_inputs.json').write_text('{}', encoding='utf-8')
    status = Workspace(ws).detect()['batch']
    assert status.status == 'blocked'
    assert 'ZERO images' in status.summary


def test_one_empty_zone_among_full_ones_is_partial(tmp_path):
    ws = tmp_path / 'cruise'
    batched = ws / 'batched_images_by_zone'
    for zone in ('zone_1', 'zone_2'):
        (batched / zone).mkdir(parents=True)
    (batched / 'zone_1' / 'a.jpg').write_bytes(b'j')
    (batched / 'batch_inputs.json').write_text('{}', encoding='utf-8')
    status = Workspace(ws).detect()['batch']
    assert status.status == 'partial'
    assert 'zone_2' in status.summary


def test_full_zones_are_done(tmp_path):
    ws = tmp_path / 'cruise'
    batched = ws / 'batched_images_by_zone'
    for zone in ('zone_1', 'zone_2'):
        (batched / zone).mkdir(parents=True)
        (batched / zone / 'a.jpg').write_bytes(b'j')
    (batched / 'batch_inputs.json').write_text('{}', encoding='utf-8')
    assert Workspace(ws).detect()['batch'].status == 'done'


# --------------------------------------------------------- export denominator

def test_a_partial_export_is_measured_against_the_merge_report(tmp_path):
    """Measured: 1 exported component with 6 finals declared read
    'done | 1 component(s) exported'."""
    ws = tmp_path / 'cruise'
    ws.mkdir()
    _merged(ws)
    d = ws / 'exports' / 'zone_1_c0' / 'obj'
    d.mkdir(parents=True)
    (d / 'zone_1_c0.obj').write_bytes(b'o')
    status = Workspace(ws).detect()['export']
    assert status.status == 'partial'
    assert 'zone_2_c0' in status.summary, status.summary


def test_a_complete_export_is_done(tmp_path):
    ws = tmp_path / 'cruise'
    ws.mkdir()
    _merged(ws)
    for comp in ('zone_1_c0', 'zone_2_c0'):
        d = ws / 'exports' / comp / 'obj'
        d.mkdir(parents=True)
        (d / f'{comp}.obj').write_bytes(b'o')
    assert Workspace(ws).detect()['export'].status == 'done'


# -------------------------------------------------------- merge gate honesty

def test_the_gate_file_alone_is_not_merge_success(tmp_path):
    """merge_zones wrote EVALUATION_READY before checking the assembly
    result, so the census could read a never-saved project as done."""
    ws = tmp_path / 'cruise'
    ws.mkdir()
    report = json.loads(json.dumps(MERGE_REPORT))
    report['assembly']['workflow_success'] = False
    _merged(ws, report)
    status = Workspace(ws).detect()['merge']
    assert status.status == 'blocked'
    assert 'FAILED' in status.summary


def test_a_report_without_an_assembly_block_still_censuses(tmp_path):
    """Older reports have no 'assembly' key - absent is not failure."""
    ws = tmp_path / 'cruise'
    ws.mkdir()
    report = {k: v for k, v in MERGE_REPORT.items() if k != 'assembly'}
    _merged(ws, report)
    assert Workspace(ws).detect()['merge'].status == 'done'


# --------------------------------------------------------- wrong-shape JSON

@pytest.mark.parametrize('report', [
    {'clusters': {'a': 1}, 'input_scales': []},
    {'clusters': ['a string', 3], 'input_scales': None},
    {'clusters': [{'final_components': 'nope'}]},
    {'clusters': [{'final_components': ['x']}]},
    [],
])
def test_a_wrong_shape_merge_report_never_raises(tmp_path, report):
    """_load_json guarded I/O and JSON errors but not SHAPE:
    `AttributeError: 'str' object has no attribute 'get'`."""
    ws = tmp_path / 'cruise'
    merge = ws / 'final_assembly'
    (merge / 'assembly').mkdir(parents=True)
    (merge / 'merge_report.json').write_text(json.dumps(report),
                                             encoding='utf-8')
    workspace = Workspace(ws)
    statuses = workspace.detect()          # must not raise
    assert statuses['merge'].status in ('partial', 'pending', 'blocked')
    assert workspace.components() == []


def test_records_helper():
    assert _records({'clusters': [{'a': 1}, 'junk', 3]}, 'clusters') == \
        [{'a': 1}]
    assert _records({'clusters': {'k': {'a': 1}}}, 'clusters') == [{'a': 1}]
    assert _records({}, 'clusters') == []
    assert _records({'models': [], 'components': [{'a': 1}]},
                    'models', 'components') == [{'a': 1}]


# ----------------------------------------------------- driver postconditions

def test_finish_model_expects_the_obj_and_its_mtl(tmp_path):
    """A textured OBJ without its .mtl is an untextured OBJ to every
    consumer."""
    assert finish_model.missing_exports(str(tmp_path), 'Final', 'objmetric')
    (tmp_path / 'Final.obj').write_bytes(b'o')
    still = finish_model.missing_exports(str(tmp_path), 'Final', 'objmetric')
    assert len(still) == 1 and still[0].endswith('Final.mtl')
    (tmp_path / 'Final.mtl').write_bytes(b'm')
    assert finish_model.missing_exports(str(tmp_path), 'Final',
                                        'objmetric') == []


def test_finish_model_rejects_a_zero_length_deliverable(tmp_path):
    (tmp_path / 'Final.obj').write_bytes(b'')
    (tmp_path / 'Final.mtl').write_bytes(b'm')
    missing = finish_model.missing_exports(str(tmp_path), 'Final', 'obj')
    assert any(m.endswith('Final.obj') for m in missing)


def test_finish_model_format_none_expects_nothing(tmp_path):
    assert finish_model.missing_exports(str(tmp_path), 'Final', 'none') == []


def _finish_model_run(tmp_path, monkeypatch, produce):
    """finish_model.main() against a stubbed attach that always SUCCEEDS.

    The whole point: RealityScan reports success for do-nothing exports,
    so the driver must not take success at its word (ModelToFinal is the
    current branch's entire purpose, and run_attach_script has no
    post-condition of its own)."""
    from modules.realityscan_interface.realityscan_cli import (
        RealityScanCLI, WorkflowResult)

    outdir = tmp_path / 'final'
    outdir.mkdir()
    if produce:
        (outdir / 'Final.obj').write_bytes(b'o')
        (outdir / 'Final.mtl').write_bytes(b'm')

    monkeypatch.setattr(
        RealityScanCLI, 'run_attach_script',
        lambda self, *a, **k: WorkflowResult(True, 0, 'log.txt', '', [], 1.0))
    monkeypatch.setattr(finish_model, 'SettingsStore', lambda *a, **k: _Store())
    monkeypatch.setattr(finish_model, 'realityscan_env', lambda store: {})
    monkeypatch.setattr(sys, 'argv',
                        ['finish_model.py', '--outdir', str(outdir),
                         '--instance', 'RS1'])
    return finish_model.main()


class _Store:
    """SettingsStore stand-in so the drivers never touch rs_settings.json."""

    def get(self, *a, **k):
        return None

    def set(self, *a, **k):
        pass

    def ask(self, _section, _key, cli_value, fallback):
        return cli_value if cli_value is not None else fallback


def test_finish_model_refuses_success_over_an_empty_export_dir(tmp_path,
                                                               monkeypatch):
    assert _finish_model_run(tmp_path, monkeypatch, produce=False) == 1


def test_finish_model_accepts_a_real_deliverable(tmp_path, monkeypatch):
    assert _finish_model_run(tmp_path, monkeypatch, produce=True) == 0


def test_export_postcondition_names_the_missing_folders(tmp_path):
    names = ['zone_1_c0', 'zone_2_c0']
    for kind in ('obj', 'fbx', 'ply'):
        d = tmp_path / 'zone_1_c0' / kind
        d.mkdir(parents=True)
        (d / f'zone_1_c0.{kind}').write_bytes(b'x')
    missing = export_deliverables.missing_exports(str(tmp_path), names)
    assert sorted(missing) == ['zone_2_c0/fbx', 'zone_2_c0/obj',
                               'zone_2_c0/ply']


def test_export_postcondition_rejects_an_empty_file(tmp_path):
    for kind in ('obj', 'fbx', 'ply'):
        d = tmp_path / 'c0' / kind
        d.mkdir(parents=True)
        (d / f'c0.{kind}').write_bytes(b'' if kind == 'ply' else b'x')
    assert export_deliverables.missing_exports(str(tmp_path), ['c0']) == \
        ['c0/ply']


def test_read_component_names_is_bom_tolerant(tmp_path):
    path = tmp_path / 'components.names'
    path.write_bytes('﻿zone_1_c0\r\n\r\nzone_2_c0\r\n'.encode('utf-8'))
    assert export_deliverables.read_component_names(str(path)) == \
        ['zone_1_c0', 'zone_2_c0']


def _export_driver_run(tmp_path, monkeypatch, produce):
    """export_deliverables.main() against a stubbed workflow that always
    SUCCEEDS - the do-nothing-export case the .bat's own comment records
    ('exports are selection-driven ... exports NOTHING, census read 0')."""
    from modules.realityscan_interface.realityscan_cli import WorkflowResult

    project = tmp_path / 'Assembly.rsproj'
    project.write_bytes(b'p')
    names = tmp_path / 'components.names'
    names.write_text('c0\n', encoding='utf-8')
    exports = tmp_path / 'exports'
    exports.mkdir()
    if produce:
        for kind in export_deliverables.EXPORT_KINDS:
            d = exports / 'c0' / kind
            d.mkdir(parents=True)
            (d / f'c0.{kind}').write_bytes(b'x')

    monkeypatch.setattr(export_deliverables, 'run_export',
                        lambda *a, **k: WorkflowResult(True, 0, 'log.txt',
                                                       '', [], 1.0))
    monkeypatch.setattr(export_deliverables, 'SettingsStore',
                        lambda *a, **k: _Store())
    monkeypatch.setattr(sys, 'argv',
                        ['export_deliverables.py', '--project', str(project),
                         '--exports', str(exports), '--names', str(names)])
    return export_deliverables.main()


def test_export_driver_refuses_success_over_empty_folders(tmp_path,
                                                          monkeypatch):
    assert _export_driver_run(tmp_path, monkeypatch, produce=False) == 1


def test_export_driver_accepts_real_deliverables(tmp_path, monkeypatch):
    assert _export_driver_run(tmp_path, monkeypatch, produce=True) == 0


@pytest.mark.parametrize('content', ['', '\r\n\r\n', '   \n\t\n'])
def test_export_driver_refuses_an_empty_name_list(tmp_path, content):
    """The .bat's `for /f` runs ZERO iterations on this, -quits and exits
    0 - a no-op that reports success."""
    project = tmp_path / 'Assembly.rsproj'
    project.write_bytes(b'p')
    names = tmp_path / 'components.names'
    names.write_text(content, encoding='utf-8')
    proc = subprocess.run(
        [sys.executable,
         os.path.join(REPO_ROOT, 'modules', 'export_deliverables.py'),
         '--project', str(project), '--exports', str(tmp_path / 'exports'),
         '--names', str(names)],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
        cwd=REPO_ROOT)
    assert proc.returncode == 1
    assert 'names NOTHING' in (proc.stderr + proc.stdout)


# ------------------------------------------------------- run_models guards

@pytest.mark.parametrize('kind', ['missing', 'file'])
def test_run_models_workspace_is_validated_before_logging(tmp_path, kind):
    """The FileHandler is opened inside the workspace, so a mistyped path
    died with a FileNotFoundError traceback out of basicConfig - the exact
    bug direct mode already fixed."""
    if kind == 'missing':
        target = tmp_path / 'does_not_exist'
    else:
        target = tmp_path / 'a_file'
        target.write_text('x', encoding='utf-8')
    proc = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, 'run_models.py'),
         '--workspace', str(target)],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
        cwd=REPO_ROOT)
    assert proc.returncode == 1
    assert 'Traceback' not in proc.stderr, proc.stderr
    assert 'workspace not found' in proc.stderr


def test_run_models_disk_floor_uses_the_workspace_path():
    """Path('ws').drive is '' for a relative --workspace, so `drive+'\\\\'`
    became '\\\\' and the 50 GB floor measured the SYSTEM drive."""
    source = open(os.path.join(REPO_ROOT, 'run_models.py'),
                  encoding='utf-8').read()
    assert "shutil.disk_usage(ws.root)" in source
    assert "ws.root.drive + '\\\\'" not in source


def test_run_models_refuses_a_merge_report_with_no_final_components(tmp_path):
    """A merge report that declares nothing final gave `finals == []`, and
    the loop below it ran zero iterations, wrote a models_report.json with
    an empty 'models' list and returned 0 - the do-nothing-reports-success
    shape, one level up from the workflow (audit-verification 2026-08-07:
    the guard shipped with no test)."""
    merge = tmp_path / 'final_assembly'
    (merge / 'assembly').mkdir(parents=True)
    (merge / 'assembly' / 'Assembly.rsproj').write_bytes(b'p')
    (merge / 'merge_report.json').write_text(
        json.dumps({'clusters': [{'cluster': 'c0', 'final_components': []}]}),
        encoding='utf-8')
    (merge / 'flight_log_53N_UTM.txt').write_text(
        'filename;X (East);Y (North)\na.jpg;1;2\n', encoding='utf-8')
    proc = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, 'run_models.py'),
         '--workspace', str(tmp_path)],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
        cwd=REPO_ROOT)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert 'declares no final components' in (proc.stdout + proc.stderr)
    # No RealityScan was booted and no report was written.
    assert not (tmp_path / 'models_report.json').exists()


# ------------------------------------------------- publish input CRS (driver)

def _publish_ws(tmp_path, log_names):
    """A workspace with exported deliverables and the given flight logs."""
    import publish_batch                                    # noqa: PLC0415
    exports = tmp_path / 'exports' / 'zone_1_c0' / 'obj'
    exports.mkdir(parents=True)
    (exports / 'zone_1_c0.obj').write_text('v 0 0 0\n', encoding='utf-8')
    (tmp_path / 'raw_images').mkdir()
    for rel in log_names:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('filename;X (East);Y (North)\na.jpg;1;2\n',
                        encoding='utf-8')
    return publish_batch


def test_publish_resolves_the_input_crs_from_the_workspace(tmp_path):
    """The OBJ exports carry raw UTM metres (MvsExportIsGeoreferenced,
    scale 1.0, no offset), so publishing them with no CRS puts the asset in
    the wrong part of the world. The portal pins --input-crs; the
    STANDALONE driver has to resolve it itself, and that half shipped
    untested (audit-verification 2026-08-07)."""
    pb = _publish_ws(tmp_path, ['raw_images/flight_log_54L_UTM.txt'])
    assert pb.resolve_input_crs(tmp_path) == 'EPSG:32754'


def test_publish_prefers_the_merge_union_log(tmp_path):
    """The exported components were built against the merge's union log."""
    pb = _publish_ws(tmp_path, ['raw_images/flight_log_53N_UTM.txt',
                                'final_assembly/flight_log_53N_UTM.txt'])
    assert pb.resolve_input_crs(tmp_path) == 'EPSG:32653'


def test_publish_has_no_crs_for_a_local_frame_campaign(tmp_path):
    pb = _publish_ws(tmp_path, ['raw_images/flight_log_local_UTM.txt'])
    assert pb.resolve_input_crs(tmp_path) is None


def test_publish_refuses_disagreeing_zones_rather_than_picking_one(tmp_path):
    pb = _publish_ws(tmp_path, ['raw_images/flight_log_53N_UTM.txt',
                                'raw_images/flight_log_57L_UTM.txt'])
    with pytest.raises(SystemExit) as exc:
        pb.resolve_input_crs(tmp_path)
    assert 'cannot resolve a flight log' in str(exc.value)


def test_the_publish_driver_passes_the_georeferencing_downstream(tmp_path):
    """End to end through main(): the georeferencing input was only
    forwarded when the OPERATOR typed it, so every portal-free publish
    shipped without one (audit-verification 2026-08-07).

    The mechanism changed on 2026-08-31: placement now comes from each
    mesh's own .rsInfo sidecar, and the flight log is forwarded instead as
    the INDEPENDENT nav check on that reading. What must not regress is that
    the driver resolves it itself and passes it on.
    """
    _publish_ws(tmp_path, ['raw_images/flight_log_54L_UTM.txt'])
    proc = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, 'publish_batch.py'),
         '--workspace', str(tmp_path), '--prefix', 'NA167', '--dry-run'],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
        cwd=REPO_ROOT)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert '--flight-log' in combined, combined[-800:]
    assert 'flight_log_54L_UTM.txt' in combined, combined[-800:]
    # and the publish itself must be verified, not fire-and-forget
    assert '--verify' in combined, combined[-800:]
