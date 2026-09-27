#!/usr/bin/env python3
"""publish_batch publishes a NAMED export tree and keeps its own record.

WHY THIS EXISTS. NA165/H2060's re-export lands in proc/deliver_L/exports/
<comp>_L/ beside the delivered proc/exports/<comp>/, and both stay on disk
until the new assets verify. publish_batch could only read
<workspace>/exports and rebuilt <workspace>/publish_report.json from scratch
on every run, so:

  - publishing the new tree meant pointing --workspace at it and hoping the
    old report was elsewhere; a slip published the OLD generation again;
  - a resumed run erased the first run's records (the delivered report
    lists 38 of the 39 assets published) and would re-upload everything;
  - the ion asset id went nowhere machine-readable: publish_cesium logs it
    to stderr, publish_batch captures stdout - so the old->new id table the
    owner's D10 decision needs had to be rebuilt from ion by name.

The review of that change (2026-09-27) added the rest: a corrupt report must
stop the run rather than restart it, skipping is per destination, a result
JSON from an earlier run is never merged, previews stay out of the record,
the census reads the NEWEST record per component, and no staging directory
may sit on top of an export.

No network, no ion: publish_batch.run is replaced by a recorder and
publish_cesium is never spawned. The token is a placeholder string. The
publish_cesium tests stage for real (--dry-run) or mock the ion session.

Run:  python -m pytest testing/test_publish_batch_tree.py
"""
from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO_ROOT)

import publish_batch as pb  # noqa: E402
from modules.workspace_census import Workspace  # noqa: E402


def _tree(root: Path, names):
    for name in names:
        d = root / name / 'obj'
        d.mkdir(parents=True)
        (d / f'{name}_0000000.obj').write_text('v 0 0 0\n', encoding='utf-8')
    return root


def _run_main(monkeypatch, argv, asset_ids=None, token=True, nira=False,
              fail=(), nira_fail=(), write_result=True):
    """publish_batch.main with run() replaced. ``fail`` / ``nira_fail`` name
    assets whose upload exits 1; a failing publish_cesium writes no result
    JSON, like one that dies early."""
    calls = []

    def fake_run(cmd, dry_run):
        calls.append(cmd)
        if dry_run:
            return {'command': ' '.join(cmd), 'dry_run': True}
        name = cmd[cmd.index('--name') + 1]
        if 'publish_nira.py' in cmd[1]:
            ok = name not in nira_fail
            return {'command': ' '.join(cmd), 'returncode': 0 if ok else 1,
                    'success': ok}
        if name in fail:
            return {'command': ' '.join(cmd), 'returncode': 1, 'success': False}
        if write_result and '--result-json' in cmd and asset_ids is not None:
            out = Path(cmd[cmd.index('--result-json') + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({'name': name, 'asset_id': asset_ids[name],
                                       'status': 'COMPLETE', 'verified': True,
                                       'exit_code': 0}), encoding='utf-8')
        return {'command': ' '.join(cmd), 'returncode': 0, 'success': True}

    monkeypatch.setattr(pb, 'run', fake_run)
    if nira:
        monkeypatch.setenv('NIRACLIENT_DIR', 'placeholder-niraclient')
    else:
        monkeypatch.delenv('NIRACLIENT_DIR', raising=False)
    if token:
        monkeypatch.setenv('CESIUM_ION_TOKEN', 'placeholder-not-a-token')
    else:
        monkeypatch.delenv('CESIUM_ION_TOKEN', raising=False)
    monkeypatch.setattr(sys, 'argv', ['publish_batch.py'] + argv)
    return pb.main(), calls


def _arg(cmd, flag):
    return cmd[cmd.index(flag) + 1]


def _published(component, asset_id, name=None):
    return {'component': component, 'asset_name': name or f'P {component}',
            'cesium': {'success': True, 'asset_id': asset_id,
                       'status': 'COMPLETE', 'verified': True}}


def test_asset_names_come_from_the_tree_directory_names(tmp_path, monkeypatch):
    exports = _tree(tmp_path / 'deliver_L' / 'exports', ['zone_1_c0_L', 'zone_2_c3_L'])
    rc, calls = _run_main(monkeypatch, [
        '--workspace', str(tmp_path), '--exports', str(exports),
        '--prefix', 'NA165 H2060', '--dry-run'], token=False)
    assert rc == 0
    names = [_arg(c, '--name') for c in calls if 'publish_cesium.py' in c[1]]
    assert names == ['NA165 H2060 zone_1_c0_L', 'NA165 H2060 zone_2_c3_L']
    dirs = [_arg(c, '--dir') for c in calls if 'publish_cesium.py' in c[1]]
    assert all('deliver_L' in d for d in dirs)
    assert all('--poll' in c and '--verify' in c for c in calls
               if 'publish_cesium.py' in c[1])


def test_the_description_is_templated_per_asset(tmp_path, monkeypatch):
    exports = _tree(tmp_path / 'x', ['zone_1_c0_L'])
    _, calls = _run_main(monkeypatch, [
        '--workspace', str(tmp_path), '--exports', str(exports),
        '--prefix', 'NA165 H2060', '--require-suffix', '_L', '--dry-run',
        '--description', 'Component {stem} ({component}); {asset_name}; {other}'],
        token=False)
    assert _arg(calls[0], '--description') == (
        'Component zone_1_c0 (zone_1_c0_L); NA165 H2060 zone_1_c0_L; {other}')


def test_the_wrong_generation_is_refused(tmp_path, monkeypatch):
    """Pointing at the delivered tree by mistake must publish nothing."""
    _tree(tmp_path / 'exports', ['zone_1_c0', 'zone_2_c3'])
    with pytest.raises(SystemExit, match='do not end with'):
        _run_main(monkeypatch, ['--workspace', str(tmp_path), '--prefix', 'P',
                                '--require-suffix', '_L', '--dry-run'], token=False)


def test_the_report_is_appended_to_and_carries_the_asset_id(tmp_path, monkeypatch):
    _tree(tmp_path / 'exports', ['c1_L', 'c2_L'])
    report = tmp_path / 'reports' / 'publish_report.json'
    report.parent.mkdir()
    report.write_text(json.dumps({'started': 'earlier', 'assets': [
        {'component': 'old', 'cesium': {'success': True, 'asset_id': 1}}]}),
        encoding='utf-8')
    rc, calls = _run_main(monkeypatch, [
        '--workspace', str(tmp_path), '--prefix', 'P', '--report', str(report)],
        asset_ids={'P c1_L': 101, 'P c2_L': 102})
    assert rc == 0
    data = json.loads(report.read_text(encoding='utf-8'))
    assert [a['component'] for a in data['assets']] == ['old', 'c1_L', 'c2_L']
    assert [a['cesium'].get('asset_id') for a in data['assets']] == [1, 101, 102]
    assert data['started'] == 'earlier' and len(data['runs']) == 1
    # one results folder per run; the id table is built from these
    results = list((report.parent / 'publish_report_results').glob('*/c1_L.json'))
    assert len(results) == 1


def test_skip_published_resumes_instead_of_reuploading(tmp_path, monkeypatch):
    _tree(tmp_path / 'exports', ['c1_L', 'c2_L'])
    report = tmp_path / 'publish_report.json'
    report.write_text(json.dumps({'assets': [_published('c1_L', 101)]}),
                      encoding='utf-8')
    rc, calls = _run_main(monkeypatch, [
        '--workspace', str(tmp_path), '--prefix', 'P', '--skip-published'],
        asset_ids={'P c2_L': 102})
    assert rc == 0
    assert [_arg(c, '--name') for c in calls] == ['P c2_L']
    data = json.loads(report.read_text(encoding='utf-8'))
    assert data['runs'][-1]['skipped'] == ['c1_L']


def test_a_failed_or_dry_record_does_not_count_as_published(tmp_path, monkeypatch):
    _tree(tmp_path / 'exports', ['c1_L'])
    report = tmp_path / 'publish_report.json'
    report.write_text(json.dumps({'assets': [
        {'component': 'c1_L', 'asset_name': 'P c1_L',
         'cesium': {'success': False, 'asset_id': 7}},
        {'component': 'c1_L', 'asset_name': 'P c1_L', 'cesium': {'dry_run': True}}]}),
        encoding='utf-8')
    _, calls = _run_main(monkeypatch, [
        '--workspace', str(tmp_path), '--prefix', 'P', '--skip-published'],
        asset_ids={'P c1_L': 8})
    assert len(calls) == 1


@pytest.mark.parametrize('record', [
    {'success': True, 'asset_id': 5, 'status': 'COMPLETE'},             # not verified
    {'success': True, 'asset_id': 5, 'status': 'ERROR', 'verified': True},
    {'success': True, 'status': 'COMPLETE', 'verified': True},           # pre-patch shape
])
def test_only_a_verified_complete_asset_is_skipped(tmp_path, monkeypatch, record):
    _tree(tmp_path / 'exports', ['c1_L'])
    report = tmp_path / 'publish_report.json'
    report.write_text(json.dumps({'assets': [
        {'component': 'c1_L', 'asset_name': 'P c1_L', 'cesium': record}]}),
        encoding='utf-8')
    _, calls = _run_main(monkeypatch, [
        '--workspace', str(tmp_path), '--prefix', 'P', '--skip-published'],
        asset_ids={'P c1_L': 8})
    assert len(calls) == 1


def test_a_record_under_another_asset_name_is_not_skipped(tmp_path, monkeypatch):
    """A different --prefix is a different ion asset."""
    _tree(tmp_path / 'exports', ['c1_L'])
    report = tmp_path / 'publish_report.json'
    report.write_text(json.dumps({'assets': [_published('c1_L', 101, 'OLD c1_L')]}),
                      encoding='utf-8')
    _, calls = _run_main(monkeypatch, [
        '--workspace', str(tmp_path), '--prefix', 'P', '--skip-published'],
        asset_ids={'P c1_L': 8})
    assert [_arg(c, '--name') for c in calls] == ['P c1_L']


def test_skipping_is_per_destination(tmp_path, monkeypatch):
    """Cesium verified, Nira failed: the rerun must retry Nira ONLY (it used
    to skip the whole component and report success)."""
    _tree(tmp_path / 'exports', ['c1_L'])
    report = tmp_path / 'publish_report.json'
    rc1, _ = _run_main(monkeypatch, ['--workspace', str(tmp_path), '--prefix', 'P'],
                       asset_ids={'P c1_L': 101}, nira=True, nira_fail={'P c1_L'})
    assert rc1 == 1
    rc2, calls = _run_main(monkeypatch, ['--workspace', str(tmp_path), '--prefix', 'P',
                                         '--skip-published'],
                           asset_ids={'P c1_L': 999}, nira=True)
    assert rc2 == 0
    assert [c[1].endswith('publish_nira.py') for c in calls] == [True]
    last = json.loads(report.read_text(encoding='utf-8'))['assets'][-1]
    assert last['cesium'] == {'skipped': True, 'asset_id': 101}
    assert last['nira']['success'] is True


def test_a_dry_run_says_what_would_be_skipped(tmp_path, monkeypatch):
    _tree(tmp_path / 'exports', ['c1_L', 'c2_L'])
    report = tmp_path / 'publish_report.json'
    before = json.dumps({'assets': [_published('c1_L', 101)]})
    report.write_text(before, encoding='utf-8')
    _, calls = _run_main(monkeypatch, [
        '--workspace', str(tmp_path), '--prefix', 'P', '--skip-published',
        '--dry-run'], token=False)
    ces = [_arg(c, '--name') for c in calls if 'publish_cesium.py' in c[1]]
    assert ces == ['P c2_L']
    assert report.read_text(encoding='utf-8') == before, 'a preview wrote the record'
    preview = json.loads((tmp_path / 'publish_report.dry_run.json')
                         .read_text(encoding='utf-8'))
    assert preview['dry_run_of'] == str(report)
    assert preview['assets'][0]['cesium'] == {'skipped': True, 'asset_id': 101}


def test_a_run_that_skips_everything_still_records_the_run(tmp_path, monkeypatch):
    _tree(tmp_path / 'exports', ['c1_L'])
    report = tmp_path / 'publish_report.json'
    report.write_text(json.dumps({'assets': [_published('c1_L', 101)]}),
                      encoding='utf-8')
    rc, calls = _run_main(monkeypatch, ['--workspace', str(tmp_path), '--prefix', 'P',
                                        '--skip-published'])
    assert rc == 0 and calls == []
    data = json.loads(report.read_text(encoding='utf-8'))
    assert data['runs'][-1]['skipped'] == ['c1_L'] and len(data['assets']) == 1


@pytest.mark.parametrize('content', ['{"assets": [{"component": "c1_L", "ces',
                                     '[{"component": "c1_L"}]',
                                     '{"started": "x"}'])
def test_an_unreadable_report_stops_the_run_and_survives(tmp_path, monkeypatch, content):
    """Treating it as empty overwrote every earlier record and, with
    --skip-published, re-published (duplicated) every asset."""
    _tree(tmp_path / 'exports', ['c1_L'])
    report = tmp_path / 'publish_report.json'
    report.write_text(content, encoding='utf-8')
    with pytest.raises(SystemExit, match='publish report'):
        _run_main(monkeypatch, ['--workspace', str(tmp_path), '--prefix', 'P',
                                '--skip-published'], asset_ids={'P c1_L': 8})
    assert report.read_text(encoding='utf-8') == content


def test_a_result_json_from_an_earlier_run_is_never_merged(tmp_path, monkeypatch):
    """publish_cesium that dies before writing its record must not inherit
    the previous run's asset id, COMPLETE and verified."""
    _tree(tmp_path / 'exports', ['c1_L'])
    report = tmp_path / 'publish_report.json'
    _run_main(monkeypatch, ['--workspace', str(tmp_path), '--prefix', 'P'],
              asset_ids={'P c1_L': 101})
    rc, _ = _run_main(monkeypatch, ['--workspace', str(tmp_path), '--prefix', 'P'],
                      fail={'P c1_L'})
    assert rc == 1
    last = json.loads(report.read_text(encoding='utf-8'))['assets'][-1]['cesium']
    assert last['success'] is False
    assert 'asset_id' not in last and 'verified' not in last


def test_this_run_decides_the_exit_code(tmp_path, monkeypatch):
    """One old failure in the appended report must not fail later runs."""
    _tree(tmp_path / 'exports', ['c1_L'])
    report = tmp_path / 'publish_report.json'
    report.write_text(json.dumps({'assets': [
        {'component': 'c1_L', 'asset_name': 'P c1_L',
         'cesium': {'success': False, 'returncode': 1}}]}), encoding='utf-8')
    rc, _ = _run_main(monkeypatch, ['--workspace', str(tmp_path), '--prefix', 'P'],
                      asset_ids={'P c1_L': 8})
    assert rc == 0


def test_staging_goes_outside_the_export_tree(tmp_path, monkeypatch):
    _tree(tmp_path / 'exports', ['c1_L'])
    stage = tmp_path / 'staging'
    _, calls = _run_main(monkeypatch, [
        '--workspace', str(tmp_path), '--prefix', 'P', '--dry-run',
        '--staging-root', str(stage), '--clean-staging'], token=False)
    assert Path(_arg(calls[0], '--staging')) == stage / 'c1_L'
    assert '--clean-staging' in calls[0]


@pytest.mark.parametrize('where', ['exports', 'exports/c1_L', '.'])
def test_a_staging_root_on_the_export_tree_is_refused(tmp_path, monkeypatch, where):
    """--staging-root <exports> made <exports>/<comp> the staging directory,
    which publish_cesium empties first: every obj/fbx/ply deleted."""
    exports = _tree(tmp_path / 'exports', ['c1_L'])
    with pytest.raises(SystemExit, match='--staging-root'):
        _run_main(monkeypatch, ['--workspace', str(tmp_path), '--prefix', 'P',
                                '--dry-run', '--staging-root', str(tmp_path / where)],
                  token=False)
    assert (exports / 'c1_L' / 'obj' / 'c1_L_0000000.obj').is_file()


# --------------------------------------------------------------- the census

def _census(ws):
    return Workspace(ws).detect()['publish']


def test_census_reads_the_newest_record_per_component(tmp_path, monkeypatch):
    """Appending made every retry, re-run or preview a permanent 'partial'."""
    _tree(tmp_path / 'exports', ['c1_L', 'c2_L'])
    ids = {'P c1_L': 101, 'P c2_L': 102}
    argv = ['--workspace', str(tmp_path), '--prefix', 'P']
    _run_main(monkeypatch, argv + ['--dry-run'], token=False)          # preview
    _run_main(monkeypatch, argv, asset_ids=ids, fail={'P c2_L'})       # c2 fails
    assert _census(tmp_path).status == 'partial'
    _run_main(monkeypatch, argv + ['--components', 'c2_L'], asset_ids=ids)  # retry
    status = _census(tmp_path)
    assert (status.status, status.summary) == ('done', '2 of 2 asset(s) published')
    _run_main(monkeypatch, argv, asset_ids=ids)                        # re-run
    assert _census(tmp_path).summary == '2 of 2 asset(s) published'


def test_census_ignores_skip_markers_and_previews(tmp_path):
    (tmp_path / 'publish_report.json').write_text(json.dumps({'assets': [
        _published('c1_L', 101),
        {'component': 'c1_L', 'asset_name': 'P c1_L',
         'cesium': {'skipped': True, 'asset_id': 101},
         'nira': {'success': True}},
        {'component': 'c1_L', 'asset_name': 'P c1_L', 'cesium': {'dry_run': True}},
    ]}), encoding='utf-8')
    status = _census(tmp_path)
    assert (status.status, status.summary) == ('done', '1 of 1 asset(s) published')


# ------------------------------------------------ publish_cesium's record

ECEF_CENTROID = (-6070882.485, -1174959.182, -1555435.376)
RSINFO = ('<Model globalCoordinateSystemName="epsg:32702 - WGS 84 / UTM zone 2S" '
          'exportCoordinateSystemType="3" '
          'transformToModel="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1">\n'
          '  <Header magic="5786959" version="2"/>\n</Model>\n')


def _geocentric_obj(root: Path) -> Path:
    d = root / 'c1_L' / 'obj'
    d.mkdir(parents=True)
    x, y, z = ECEF_CENTROID
    (d / 'c1_L_0000000.obj').write_text(
        ''.join('v %.3f %.3f %.3f\n' % (x + i, y, z) for i in range(3)),
        encoding='utf-8')
    (d / 'c1_L_0000000.obj.rsInfo').write_text(RSINFO, encoding='utf-8')
    ply = root / 'c1_L' / 'ply'
    ply.mkdir()
    (ply / 'c1_L_dense.ply').write_bytes(b'ply')
    return d


def _export_files(root: Path):
    return sorted(str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()
                  and '_cesium_local' not in p.parts and 'stage' not in p.parts)


def test_publish_cesium_writes_a_machine_readable_result(tmp_path, monkeypatch):
    pytest.importorskip('pyproj')
    import publish_cesium as pc
    d = _geocentric_obj(tmp_path)
    out = tmp_path / 'results' / 'c1_L.json'
    monkeypatch.setattr(sys, 'argv', [
        'publish_cesium.py', '--name', 'P c1_L', '--dir', str(d), '--dry-run',
        '--no-proj-network', '--staging', str(tmp_path / 'stage'),
        '--result-json', str(out)])
    assert pc.main() == 0
    result = json.loads(out.read_text(encoding='utf-8'))
    assert result['status'] == 'DRY_RUN' and result['asset_id'] is None
    assert result['exit_code'] == 0 and result['name'] == 'P c1_L'
    assert (tmp_path / 'stage' / pc.STAGING_MARKER).is_file()


@pytest.mark.parametrize('staging', ['obj', 'component', 'root'])
def test_publish_cesium_never_stages_on_top_of_the_export(tmp_path, monkeypatch, staging):
    """stage() EMPTIES its staging directory first - and it ran before the
    dry-run return, so a --staging that CONTAINED the export deleted it."""
    pytest.importorskip('pyproj')
    import publish_cesium as pc
    d = _geocentric_obj(tmp_path / 'exports')
    target = {'obj': d, 'component': d.parent, 'root': tmp_path}[staging]
    before = _export_files(tmp_path)
    monkeypatch.setattr(sys, 'argv', [
        'publish_cesium.py', '--name', 'P', '--dir', str(d), '--dry-run',
        '--no-proj-network', '--staging', str(target)])
    with pytest.raises(SystemExit, match='is the export directory'):
        pc.main()
    assert _export_files(tmp_path) == before


def test_publish_cesium_refuses_to_empty_a_directory_it_did_not_create(tmp_path, monkeypatch):
    pytest.importorskip('pyproj')
    import publish_cesium as pc
    d = _geocentric_obj(tmp_path)
    other = tmp_path / 'someone_elses'
    other.mkdir()
    (other / 'keep.txt').write_text('data\n', encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', [
        'publish_cesium.py', '--name', 'P', '--dir', str(d), '--dry-run',
        '--no-proj-network', '--staging', str(other)])
    with pytest.raises(SystemExit, match='did not stage'):
        pc.main()
    assert (other / 'keep.txt').read_text(encoding='utf-8') == 'data\n'


def test_the_default_staging_is_reused_without_a_marker(tmp_path, monkeypatch):
    """<dir>/_cesium_local predates the marker and has always been this
    tool's own directory; earlier runs' copies must not block a rerun."""
    pytest.importorskip('pyproj')
    import publish_cesium as pc
    d = _geocentric_obj(tmp_path)
    legacy = d / pc.DEFAULT_STAGING
    legacy.mkdir()
    (legacy / 'old.obj').write_text('v 0 0 0\n', encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', [
        'publish_cesium.py', '--name', 'P', '--dir', str(d), '--dry-run',
        '--no-proj-network'])
    assert pc.main() == 0
    assert not (legacy / 'old.obj').exists()
    assert (legacy / pc.STAGING_MARKER).is_file()


def _mock_ion(monkeypatch, pc, verified=True, upload_error=None):
    """Replace every network step of publish_cesium with recorders."""
    class _Response:
        def raise_for_status(self):
            pass

    class _Session:
        def __init__(self):
            self.headers = {}

        def request(self, *a, **k):
            return _Response()

    monkeypatch.setitem(sys.modules, 'requests', types.SimpleNamespace(Session=_Session))
    monkeypatch.setattr(pc, 'require_deps', lambda: None)
    monkeypatch.setattr(pc, 'create_asset', lambda *a, **k: {
        'assetMetadata': {'id': 4242}, 'uploadLocation': {},
        'onComplete': {'method': 'POST', 'url': 'u', 'fields': {}}})

    def upload(*a, **k):
        if upload_error:
            raise upload_error
    monkeypatch.setattr(pc, 'upload_files', upload)
    monkeypatch.setattr(pc, 'poll_until_done', lambda *a, **k: 'COMPLETE')
    monkeypatch.setattr(pc, 'read_tileset_placement', lambda *a, **k: {})
    monkeypatch.setattr(pc, 'verify_placement', lambda *a, **k: (
        (True, []) if verified else (False, ['moved 40 m'])))


def _online_argv(tmp_path, d, out, *extra):
    return ['publish_cesium.py', '--name', 'P c1_L', '--dir', str(d),
            '--no-proj-network', '--token', 'placeholder-not-a-token',
            '--poll', '--verify', '--staging', str(tmp_path / 'stage'),
            '--result-json', str(out), *extra]


def test_a_verified_upload_records_the_asset_and_cleans_only_its_staging(tmp_path, monkeypatch):
    pytest.importorskip('pyproj')
    import publish_cesium as pc
    d = _geocentric_obj(tmp_path)
    _mock_ion(monkeypatch, pc)
    out = tmp_path / 'r.json'
    before = _export_files(d.parent)
    monkeypatch.setattr(sys, 'argv', _online_argv(tmp_path, d, out, '--clean-staging'))
    assert pc.main() == 0
    result = json.loads(out.read_text(encoding='utf-8'))
    assert (result['asset_id'], result['status'], result['verified'],
            result['exit_code']) == (4242, 'COMPLETE', True, 0)
    assert not (tmp_path / 'stage').exists()
    assert _export_files(d.parent) == before


def test_a_failed_verification_keeps_staging_and_records_why(tmp_path, monkeypatch):
    pytest.importorskip('pyproj')
    import publish_cesium as pc
    d = _geocentric_obj(tmp_path)
    _mock_ion(monkeypatch, pc, verified=False)
    out = tmp_path / 'r.json'
    monkeypatch.setattr(sys, 'argv', _online_argv(tmp_path, d, out, '--clean-staging'))
    assert pc.main() == 1
    result = json.loads(out.read_text(encoding='utf-8'))
    assert result['verified'] is False and result['problems'] == ['moved 40 m']
    assert result['exit_code'] == 1
    assert (tmp_path / 'stage' / pc.STAGING_MARKER).is_file()


def test_the_asset_id_is_on_disk_before_the_upload(tmp_path, monkeypatch):
    """A crash after the ion asset exists must not lose WHICH asset it is."""
    pytest.importorskip('pyproj')
    import publish_cesium as pc
    d = _geocentric_obj(tmp_path)
    _mock_ion(monkeypatch, pc, upload_error=RuntimeError('network gone'))
    out = tmp_path / 'r.json'
    monkeypatch.setattr(sys, 'argv', _online_argv(tmp_path, d, out))
    with pytest.raises(RuntimeError):
        pc.main()
    result = json.loads(out.read_text(encoding='utf-8'))
    assert (result['asset_id'], result['status'], result['exit_code']) == (
        4242, 'CREATED', 1)
