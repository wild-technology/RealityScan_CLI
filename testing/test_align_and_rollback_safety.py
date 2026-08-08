#!/usr/bin/env python3
"""Alignment resume, per-zone honesty, and rollback safety.

Alignment (audit 2026-08-07):
  - an align-only resume - the state default_enabled() produces once
    batching is done - passed the batched ROOT as rs_input_image_dir, and
    -addFolder's recursion fused EVERY zone into ONE scene. Measured with
    a stubbed CLI: 1 scene named 'batched_images_by_zone' instead of one
    per zone. Exit status and logs were identical either way.
  - 'Zones Failed: 9' with one success returned Success=True and exit 0.
  - a zone skipped for holding no images appeared in NO tally.
  - the calibration-sidecar repair sat AFTER the failure/no-component
    returns, i.e. it was skipped precisely when the operator re-runs -
    re-opening the FINDINGS 2026-07-25 defect (796 of 4,540 images left
    with no calibration prior, which CONFOUNDED PD-4/PD-4a).
  - a re-run rmtree'd the previous run's zone output - saved .rsproj and
    every exported .rsalign, GPU-hours - on a logger.warning, and the only
    backup (the dated RC_projects copy) is OFF by default.

Rollback (module_base/scene_checkpoint.py):
  - restore_scene deleted the live bundle BEFORE copying, with no
    free-space precheck and no exception handling, so an interrupted
    rollback left the scene path with nothing and no message saying the
    intact copy is in checkpoints/<tag>. grow_zone calls it in four places
    with no try/except.
  - checkpoint_scene rmtree'd an existing same-tag checkpoint before
    writing the replacement.

No RealityScan: run_batch_script is stubbed, and the checkpoint tests
inject OSError into shutil.copytree.

Run:  py -3.13 -m pytest testing/test_align_and_rollback_safety.py
"""
from __future__ import annotations

import logging
import os
import shutil
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO_ROOT)

from module_base import scene_checkpoint  # noqa: E402
from module_base.parameter import Parameter  # noqa: E402
from module_base.scene_checkpoint import (checkpoint_scene,  # noqa: E402
                                          restore_scene, scene_bundle)
from modules.realityscan_interface.realityscan_cli import WorkflowResult  # noqa: E402
from modules.realityscan_interface.realityscan_interface import (  # noqa: E402
    RealityScanAlignment)

QUIET = logging.getLogger('align-test')
QUIET.addHandler(logging.NullHandler())
QUIET.propagate = False

LOG_HEADER = 'filename;X (East);Y (North);Alt\n'


def _param(name, value, default=None):
    p = Parameter(name, None, name, type(value) if value is not None else str,
                  default, prompt_user=False)
    p.set_value(value)
    return p


def _batched(root, zones=('zone_1', 'zone_2'), with_log=True, images=True):
    batched = root / 'batched_images_by_zone'
    for zone in zones:
        z = batched / zone / 'port'
        z.mkdir(parents=True)
        if images:
            (z / f'{zone}_a.jpg').write_bytes(b'j')
        if with_log:
            (batched / zone / 'flight_log_53N_UTM.txt').write_text(
                LOG_HEADER, encoding='utf-8')
    return batched


def _module_with_stub(tmp_path, monkeypatch, params, results=None,
                      produce=False):
    """RealityScanAlignment whose only RealityScan call is recorded.

    ``produce=True`` makes a successful stub run leave the artifacts a
    real AlignZone.bat would (the saved .rsproj plus one exported
    .rsalign), so the zone counts as SUCCEEDED rather than
    'no components exported'."""
    module = RealityScanAlignment(QUIET)
    module.params = params
    queued: list[tuple] = []

    def fake_run(script, args, log_dir, display_output=False, **kw):
        queued.append((script, tuple(args)))
        result = (results.pop(0) if results is not None
                  else WorkflowResult(True, 0, None, '', [], 0.0))
        if produce and result.success:
            out_dir, scene = args[1], args[4]
            with open(os.path.join(out_dir, f'{scene}.rsproj'), 'wb') as fh:
                fh.write(b'project')
            with open(os.path.join(out_dir, f'{scene}_c0.rsalign'), 'wb') as fh:
                fh.write(b'component')
        return result

    monkeypatch.setattr(module.cli, 'run_batch_script', fake_run)
    monkeypatch.setattr(module, '_initialize_loading_bar',
                        lambda *a, **k: None)
    monkeypatch.setattr(module, '_update_loading_bar', lambda *a, **k: None)
    return module, queued


# ---------------------------------------------------- zone-container resume

def test_a_batched_root_is_expanded_per_zone(tmp_path, monkeypatch):
    """The align-only resume path. rs_input_image_dir pointing at the
    batched root produced ONE fused scene, silently nullifying the
    zoning."""
    batched = _batched(tmp_path)
    params = {
        'output_dir': _param('output_dir', str(tmp_path)),
        'rs_input_image_dir': _param('rs_input_image_dir', str(batched)),
        'rs_display_output': _param('rs_display_output', False),
        'rs_model_generate': _param('rs_model_generate', False),
        'rs_model_cull_poly': _param('rs_model_cull_poly', False),
        'rs_model_texture': _param('rs_model_texture', False),
        'rs_model_simplify': _param('rs_model_simplify', False),
        'rs_project_label': _param('rs_project_label', ''),
    }
    module, queued = _module_with_stub(tmp_path, monkeypatch, params)
    module.run()
    scenes = sorted(args[4] for _script, args in queued)
    assert scenes == ['zone_1', 'zone_2'], scenes
    assert 'batched_images_by_zone' not in scenes


def test_a_plain_image_folder_is_still_one_scene(tmp_path, monkeypatch):
    """The guard must not turn an ordinary folder of images into zones."""
    images = tmp_path / 'my_images'
    (images / 'port').mkdir(parents=True)
    (images / 'port' / 'a.jpg').write_bytes(b'j')
    params = {
        'output_dir': _param('output_dir', str(tmp_path)),
        'rs_input_image_dir': _param('rs_input_image_dir', str(images)),
        'rs_display_output': _param('rs_display_output', False),
        'rs_model_generate': _param('rs_model_generate', False),
        'rs_model_cull_poly': _param('rs_model_cull_poly', False),
        'rs_model_texture': _param('rs_model_texture', False),
        'rs_model_simplify': _param('rs_model_simplify', False),
        'rs_project_label': _param('rs_project_label', ''),
    }
    module, queued = _module_with_stub(tmp_path, monkeypatch, params)
    module.run()
    assert [args[4] for _s, args in queued] == ['my_images']


def test_zone_subfolders_detection(tmp_path):
    batched = _batched(tmp_path)
    assert [os.path.basename(p) for p in
            RealityScanAlignment.zone_subfolders(str(batched))] == \
        ['zone_1', 'zone_2']
    # A per-zone flight log is enough even without the zone_ prefix.
    other = tmp_path / 'other'
    (other / 'dive_a').mkdir(parents=True)
    (other / 'dive_a' / 'flight_log_53N_UTM.txt').write_text(
        LOG_HEADER, encoding='utf-8')
    assert RealityScanAlignment.zone_subfolders(str(other))
    # Per-CAMERA subfolders are NOT zones.
    plain = tmp_path / 'plain'
    (plain / 'port').mkdir(parents=True)
    (plain / 'cinema').mkdir()
    assert RealityScanAlignment.zone_subfolders(str(plain)) == []
    assert RealityScanAlignment.zone_subfolders(str(tmp_path / 'nope')) == []


def test_the_parameter_description_says_a_root_is_expanded():
    """The old wording ('or folder of batched images') actively invited
    the answer that fused every zone."""
    params = RealityScanAlignment(QUIET).get_parameters()
    text = params['rs_input_image_dir'].get_description()
    assert 'zone' in text.lower() and 'EXPANDED' in text.upper()


# ------------------------------------------------------------ zone tallies

def _chained_params(tmp_path):
    return {
        'output_dir': _param('output_dir', str(tmp_path)),
        'rs_display_output': _param('rs_display_output', False),
        'rs_model_generate': _param('rs_model_generate', False),
        'rs_model_cull_poly': _param('rs_model_cull_poly', False),
        'rs_model_texture': _param('rs_model_texture', False),
        'rs_model_simplify': _param('rs_model_simplify', False),
        'rs_project_label': _param('rs_project_label', ''),
    }


def test_one_failed_zone_among_successes_fails_the_run(tmp_path, monkeypatch):
    """The decisive case: 'Zones Failed: 9' WITH one success used to
    return Success=True and exit 0 - a merged deliverable missing nine
    tenths of the dive. `succeeded == 0` is not the right test."""
    _batched(tmp_path)
    results = [WorkflowResult(True, 0, None, '', [], 0.0),
               WorkflowResult(False, 1, None, 'boom', [], 0.0)]
    module, _queued = _module_with_stub(
        tmp_path, monkeypatch, _chained_params(tmp_path), results,
        produce=True)
    out = module.run()
    assert out['Zones Succeeded'] == 1, out
    assert out['Zones Failed'] == 1, out
    assert out['Success'] is False


def test_every_zone_succeeding_still_succeeds(tmp_path, monkeypatch):
    """The guard must not make a clean run look failed."""
    _batched(tmp_path)
    module, _queued = _module_with_stub(
        tmp_path, monkeypatch, _chained_params(tmp_path), produce=True)
    out = module.run()
    assert out['Zones Succeeded'] == 2 and out['Zones Failed'] == 0
    assert out['Success'] is True


def test_a_totally_failed_run_still_fails(tmp_path, monkeypatch):
    _batched(tmp_path)
    results = [WorkflowResult(False, 1, None, 'boom', [], 0.0),
               WorkflowResult(False, 1, None, 'boom', [], 0.0)]
    module, _queued = _module_with_stub(
        tmp_path, monkeypatch, _chained_params(tmp_path), results)
    out = module.run()
    assert out['Zones Succeeded'] == 0 and out['Success'] is False


def test_an_image_free_zone_is_counted_as_a_failure(tmp_path, monkeypatch):
    """A skipped zone appeared in neither 'Components' nor 'Zones Failed',
    and 'Component Count' silently excluded it."""
    _batched(tmp_path, zones=('zone_1',), images=True)
    empty = tmp_path / 'batched_images_by_zone' / 'zone_2'
    empty.mkdir(parents=True)
    (empty / 'flight_log_53N_UTM.txt').write_text(LOG_HEADER, encoding='utf-8')
    module, queued = _module_with_stub(
        tmp_path, monkeypatch, _chained_params(tmp_path), produce=True)
    out = module.run()
    assert len(queued) == 1, 'the empty zone must not be aligned'
    entries = list(out['Components'].values())
    assert any(e.get('Skipped') for e in entries), entries
    assert out['Zones Failed'] >= 1
    assert out['Success'] is False


# ----------------------------------------------- sidecar repair reachability

def test_sidecar_repair_runs_before_the_failure_returns():
    """It sat after `if not result.success: return` and after
    `if not component_files: return` - skipped exactly when the operator
    re-runs."""
    source = open(os.path.join(REPO_ROOT, 'modules', 'realityscan_interface',
                               'realityscan_interface.py'),
                  encoding='utf-8').read()
    repair = source.index('camera_registry.ensure_calibration_sidecars(')
    failure_return = source.index('if not result.success:')
    no_components = source.index('if not component_files:')
    assert repair < failure_return, 'repair is unreachable on a failed align'
    assert repair < no_components, 'repair is unreachable on a zero-component align'


def test_a_pre_existing_pose_sidecar_is_announced(tmp_path, monkeypatch):
    """Pointing the pipeline at a user-owned folder MOVES their pose
    sidecars out and never returns them - undocumented until now."""
    images = tmp_path / 'my_images'
    images.mkdir()
    (images / 'a.jpg').write_bytes(b'j')
    (images / 'a.xmp').write_text(
        '<x><xcr:Position>1 2 3</xcr:Position></x>', encoding='utf-8')

    messages = []

    class Cap(logging.Handler):
        def emit(self, record):
            messages.append(record.getMessage())

    logger = logging.getLogger('align-preflight-test')
    logger.propagate = False
    logger.setLevel(logging.WARNING)
    logger.addHandler(Cap())
    module = RealityScanAlignment(logger)
    module.params = {}
    monkeypatch.setattr(module.cli, 'run_batch_script',
                        lambda *a, **k: WorkflowResult(False, 1, None, 'x',
                                                       [], 0.0))
    module._RealityScanAlignment__align_zone(
        str(images), str(tmp_path / 'out'), 'zone_1', None, None)
    assert any('pose-bearing' in m and 'identity_r0' in m
               for m in messages), messages


def test_a_previous_runs_project_is_renamed_not_deleted(tmp_path, monkeypatch):
    """The rmtree took the saved .rsproj and every exported .rsalign -
    with no second copy anywhere in the default configuration."""
    images = tmp_path / 'images'
    images.mkdir()
    (images / 'a.jpg').write_bytes(b'j')
    out = tmp_path / 'out' / 'zone_1'
    out.mkdir(parents=True)
    (out / 'zone_1.rsproj').write_bytes(b'project')
    (out / 'zone_1_c0.rsalign').write_bytes(b'component')

    module = RealityScanAlignment(QUIET)
    module.params = {}
    monkeypatch.setattr(module.cli, 'run_batch_script',
                        lambda *a, **k: WorkflowResult(False, 1, None, 'x',
                                                       [], 0.0))
    module._RealityScanAlignment__align_zone(
        str(images), str(out), 'zone_1', None, None)

    # OUTSIDE the components root - see test_the_superseded_folder_is_not
    # _rescanned below for why a sibling was wrong.
    superseded = sorted((tmp_path / 'superseded').iterdir())
    assert len(superseded) == 1, list(tmp_path.iterdir())
    assert superseded[0].name.startswith('out_zone_1_')
    assert (superseded[0] / 'zone_1.rsproj').read_bytes() == b'project'
    assert (superseded[0] / 'zone_1_c0.rsalign').read_bytes() == b'component'
    assert out.is_dir() and not any(out.iterdir())
    assert [p.name for p in (tmp_path / 'out').iterdir()] == ['zone_1']


def test_the_superseded_folder_is_not_rescanned_as_a_zone(tmp_path,
                                                          monkeypatch):
    """The rename-aside must not leave stale manifests inside the tree the
    merge and the census both walk.

    component_analysis.load_manifests walks components_root RECURSIVELY and
    Workspace._detect_align iterates its subdirectories, so a sibling
    ``zone_1.superseded_<stamp>`` double-counted: measured on this fixture,
    the census read '2 components / 2,400 cameras across 2 zones' for ONE
    re-aligned zone, and the merge saw two manifests for one .rsalign
    (export names repeat, so the stale manifest's path resolves to the NEW
    file). rmtree could not do that - the rename-aside introduced it
    (audit-verification 2026-08-07)."""
    import json as _json

    from modules import component_analysis                    # noqa: PLC0415
    from modules.workspace_census import Workspace            # noqa: PLC0415

    images = tmp_path / 'images'
    images.mkdir()
    (images / 'a.jpg').write_bytes(b'j')
    (tmp_path / 'batched_images_by_zone' / 'zone_1').mkdir(parents=True)
    aligned = tmp_path / 'aligned_components'
    out = aligned / 'zone_1'
    out.mkdir(parents=True)
    (out / 'zone_1.rsproj').write_bytes(b'project')
    (out / 'zone_1_c0.rsalign').write_bytes(b'component')
    (out / 'zone_1_c0.rsalign.manifest.json').write_text(
        _json.dumps({'rsalign': str(out / 'zone_1_c0.rsalign'),
                     'camera_count': 1200}), encoding='utf-8')

    module = RealityScanAlignment(QUIET)
    module.params = {}
    monkeypatch.setattr(module.cli, 'run_batch_script',
                        lambda *a, **k: WorkflowResult(False, 1, None, 'x',
                                                       [], 0.0))
    module._RealityScanAlignment__align_zone(
        str(images), str(out), 'zone_1', None, None)
    # The re-run re-exports under the SAME name.
    (out / 'zone_1_c0.rsalign').write_bytes(b'component2')
    (out / 'zone_1_c0.rsalign.manifest.json').write_text(
        _json.dumps({'rsalign': str(out / 'zone_1_c0.rsalign'),
                     'camera_count': 1300}), encoding='utf-8')

    manifests = [m for m in component_analysis.load_manifests(str(aligned))
                 if os.path.isfile(m['rsalign'])]
    assert len(manifests) == 1, manifests
    assert manifests[0]['camera_count'] == 1300
    status = Workspace(tmp_path).detect()['align']
    assert '1 components' in status.summary, status.summary
    assert 'across 1 zones' in status.summary, status.summary
    # ... and the data is still there, just out of the scan path.
    kept = sorted((tmp_path / 'superseded').rglob('zone_1_c0.rsalign'))
    assert len(kept) == 1 and kept[0].read_bytes() == b'component'


def test_a_stale_folder_without_deliverables_is_still_cleared(tmp_path,
                                                              monkeypatch):
    """The clean-slate premise the files_before/after diff needs must
    survive - only PROJECTS and COMPONENTS are worth keeping."""
    images = tmp_path / 'images'
    images.mkdir()
    (images / 'a.jpg').write_bytes(b'j')
    out = tmp_path / 'out' / 'zone_1'
    out.mkdir(parents=True)
    (out / 'leftover.png').write_bytes(b'plot')

    module = RealityScanAlignment(QUIET)
    module.params = {}
    monkeypatch.setattr(module.cli, 'run_batch_script',
                        lambda *a, **k: WorkflowResult(False, 1, None, 'x',
                                                       [], 0.0))
    module._RealityScanAlignment__align_zone(
        str(images), str(out), 'zone_1', None, None)
    assert not (out / 'leftover.png').exists()
    assert not (tmp_path / 'superseded').exists()


# ------------------------------------------------------------ rollback safety

def _scene(tmp_path):
    scene_dir = tmp_path / 'scene'
    scene_dir.mkdir()
    project = scene_dir / 'zone_1.rsproj'
    project.write_bytes(b'PROJECT')
    data = scene_dir / 'zone_1'
    data.mkdir()
    (data / 'sfm0.dat').write_bytes(b'DATA')
    return str(project)


def test_restore_refuses_when_the_volume_cannot_hold_the_snapshot(
        tmp_path, monkeypatch):
    """The rollback deletes the live scene BEFORE copying, so a too-small
    volume means an empty scene path. Bundles are multi-GB and this path
    had no disk floor at all."""
    project = _scene(tmp_path)
    checkpoints = str(tmp_path / 'checkpoints')
    os.makedirs(checkpoints)
    checkpoint_scene(project, checkpoints, 'initial', QUIET)

    monkeypatch.setattr(
        scene_checkpoint.shutil, 'disk_usage',
        lambda _p: shutil._ntuple_diskusage(100, 100, 0))
    with pytest.raises(RuntimeError, match='REFUSING TO ROLL BACK'):
        restore_scene(project, checkpoints, 'initial', QUIET)
    # Nothing was deleted - that is the whole point of checking first.
    assert os.path.isfile(project)
    assert len(scene_bundle(project)) == 2


def test_an_interrupted_restore_says_where_the_intact_copy_is(tmp_path,
                                                              monkeypatch):
    """Measured: the live .rsproj AND its data folder both gone,
    scene_bundle() == [], and the run ended with no message pointing at
    checkpoints/<tag>."""
    project = _scene(tmp_path)
    checkpoints = str(tmp_path / 'checkpoints')
    os.makedirs(checkpoints)
    checkpoint_scene(project, checkpoints, 'initial', QUIET)

    real_copytree = scene_checkpoint.shutil.copytree

    def exploding(src, dst, *a, **k):
        raise OSError(28, 'No space left on device')

    monkeypatch.setattr(scene_checkpoint.shutil, 'copytree', exploding)
    with pytest.raises(RuntimeError) as exc:
        restore_scene(project, checkpoints, 'initial', QUIET)
    message = str(exc.value)
    assert 'ROLLBACK INCOMPLETE' in message
    assert os.path.join(checkpoints, 'initial') in message
    assert 'retry-safe' in message

    # ... and the promise in that message is TRUE: retrying finishes it.
    monkeypatch.setattr(scene_checkpoint.shutil, 'copytree', real_copytree)
    restore_scene(project, checkpoints, 'initial', QUIET)
    assert len(scene_bundle(project)) == 2
    assert open(project, 'rb').read() == b'PROJECT'


def test_a_good_restore_still_restores(tmp_path):
    project = _scene(tmp_path)
    checkpoints = str(tmp_path / 'checkpoints')
    os.makedirs(checkpoints)
    checkpoint_scene(project, checkpoints, 'initial', QUIET)
    with open(project, 'wb') as fh:
        fh.write(b'RUINED')
    restore_scene(project, checkpoints, 'initial', QUIET)
    assert open(project, 'rb').read() == b'PROJECT'


def test_an_interrupted_re_checkpoint_keeps_the_previous_snapshot(
        tmp_path, monkeypatch):
    """It rmtree'd the existing same-tag checkpoint FIRST. Latent today
    (grow_zone's tags are unique per pass) - but tag uniqueness is a
    caller contract, not an invariant of this function."""
    project = _scene(tmp_path)
    checkpoints = str(tmp_path / 'checkpoints')
    os.makedirs(checkpoints)
    checkpoint_scene(project, checkpoints, 'pass', QUIET)
    good = sorted(os.listdir(os.path.join(checkpoints, 'pass')))
    assert good == ['zone_1', 'zone_1.rsproj']

    def exploding(src, dst, *a, **k):
        raise OSError(28, 'No space left on device')

    monkeypatch.setattr(scene_checkpoint.shutil, 'copytree', exploding)
    with pytest.raises(OSError):
        checkpoint_scene(project, checkpoints, 'pass', QUIET)
    assert sorted(os.listdir(os.path.join(checkpoints, 'pass'))) == good


# ------------------------------------------- mixed-zone flight-log refusal

def test_disagreeing_zone_logs_fail_the_zone_not_the_process(tmp_path,
                                                             monkeypatch):
    """find_flight_log now RAISES on a directory whose logs name different
    UTM zones. Two of the three lookups in run() sat OUTSIDE any try, so
    that ValueError escaped as an unhandled traceback out of main.py - the
    batcher grew the matching catch, the aligner did not
    (audit-verification 2026-08-07). The zone must FAIL (aligning it with
    no trajectory is a materially different run), never abort the process
    and never align silently."""
    _batched(tmp_path, zones=('zone_1', 'zone_2'))
    (tmp_path / 'batched_images_by_zone' / 'zone_2'
     / 'flight_log_57L_UTM.txt').write_text(LOG_HEADER, encoding='utf-8')
    module, queued = _module_with_stub(
        tmp_path, monkeypatch, _chained_params(tmp_path), produce=True)
    out = module.run()
    assert len(queued) == 1, 'the mixed-frame zone must not be aligned'
    assert out['Success'] is False
    assert out['Zones Failed'] == 1
    assert any('disagree' in str(e.get('Error', ''))
               for e in out['Components'].values()), out['Components']


def test_a_supplied_folder_with_disagreeing_logs_is_refused(tmp_path,
                                                            monkeypatch):
    """The rs_input_image_dir branch - the other uncaught lookup.

    Note where the logs go: for a supplied folder the lookup searches
    output_dir/raw_images and output_dir, NOT the supplied folder itself
    (pre-existing behaviour, untouched by this pass)."""
    folder = tmp_path / 'my_images'
    folder.mkdir()
    (folder / 'a.jpg').write_bytes(b'j')
    for tag in ('53N', '57L'):
        (tmp_path / f'flight_log_{tag}_UTM.txt').write_text(LOG_HEADER,
                                                            encoding='utf-8')
    params = _chained_params(tmp_path)
    params['rs_input_image_dir'] = _param('rs_input_image_dir', str(folder))
    module, queued = _module_with_stub(tmp_path, monkeypatch, params)
    out = module.run()
    assert queued == [], 'nothing may be aligned on a disputed frame'
    assert out['Success'] is False


def test_a_single_zone_directory_still_aligns(tmp_path, monkeypatch):
    """The refusal must not fire on the normal batched tree."""
    _batched(tmp_path, zones=('zone_1', 'zone_2'))
    module, queued = _module_with_stub(
        tmp_path, monkeypatch, _chained_params(tmp_path), produce=True)
    out = module.run()
    assert len(queued) == 2 and out['Success'] is True
