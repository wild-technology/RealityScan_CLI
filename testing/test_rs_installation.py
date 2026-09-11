"""Pure offline installation checks: all repairs stay inside tmp_path."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from modules import flightlog_format as ff
from modules import rs_installation as rs

GUID = '{D1F2A3B4-5C6D-4E7F-8A9B-0C1D2E3F4A5B}'
OTHER = '{11111111-2222-3333-4444-555555555555}'
THIRD = '{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}'
VERSION = {'product_name': 'RealityScan', 'file_version': '2.2.0.119430',
           'product_version': '2.2.0.119430'}
FIELDS = ('Image', 'X', 'Y', 'Altitude', 'XAccuracy', 'YAccuracy',
          'AltitudeAccuracy', 'Yaw', 'Pitch', 'Roll', 'YawAccuracy',
          'PitchAccuracy', 'RollAccuracy', 'FocalLength')


def block(guid=GUID, fields=FIELDS):
    columns = ''.join(f'<{name} index="{i}" format="value"/>' for i, name in enumerate(fields))
    return (f'<format id="{guid}" desc="Example" reader="RealityScan.Import.CSVFlightLog">'
            f'<parser allowedSeparators="; &tab;">{columns}</parser></format>')


@pytest.fixture
def installation(tmp_path, monkeypatch):
    app, repo = tmp_path / 'app', tmp_path / 'repo'
    app.mkdir()
    repo.mkdir()
    (app / 'RealityScan.exe').write_bytes(b'fixture, never executed')
    for folder in (app, repo):
        (folder / 'flightlogs.xml').write_text('<FlightLogs>' + block() + '</FlightLogs>', encoding='utf-8')
        (folder / 'calibration.xml').write_text(
            '<CalibrationExport><format id="' + OTHER + '"><body>$(cameraCount)</body>'
            '</format></CalibrationExport>', encoding='utf-8')
    params = repo / 'params.xml'
    params.write_text('<Configuration><entry key="gpsLogFileFormat" value="' + GUID + '"/></Configuration>')
    monkeypatch.setattr(rs, '_read_version', lambda path: VERSION.copy())
    monkeypatch.setattr(rs, 'DEFAULT_INSTALL_DIR', str(app))
    monkeypatch.setattr(ff, 'MANAGED_FILES', tuple((name, str(repo / name))
                        for name in ('flightlogs.xml', 'calibration.xml')))
    monkeypatch.setattr(rs, 'DEFAULT_PARAMS', ((params, 'flightlogs.xml', ff.FLIGHTLOG_FORMAT_KEY),))

    def forbidden(*args, **kwargs):
        pytest.fail('Audit/repair called an automatic legacy installation method')

    for name in ('install_all_managed', 'install_repo_formats', 'assert_format_installed',
                 'assert_calibration_format_installed'):
        monkeypatch.setattr(ff, name, forbidden)
    return app, repo, params


def missing(app):
    path = app / 'flightlogs.xml'
    # BOM, CRLF, non-ASCII, CDATA, comment fake tags and custom entity.
    path.write_bytes(('\ufeff<FlightLogs vendorVersion="custom">\r\n'
                      '<!-- café <format id="fake"> -->\r\n' + block(THIRD) +
                      '<unknown><![CDATA[<format>vendor opaque data</format>]]></unknown>\r\n'
                      '</FlightLogs>\r\n').encode('utf-8'))
    return path


def test_default_only_never_falls_back_or_inherits_environment(installation, monkeypatch):
    app, repo, _ = installation
    assert rs.validate_installation()['valid']
    monkeypatch.setenv('RS_EXECUTABLE', str(app / 'RealityScan.exe'))
    monkeypatch.setattr(rs, 'DEFAULT_INSTALL_DIR', str(repo))
    report = rs.validate_installation()
    assert not report['valid']
    assert '--install-dir' in report['diagnostics'][-1]
    assert rs.validate_installation(app)['valid']


@pytest.mark.parametrize('key,value', [
    ('file_version', '2.1.0.123'), ('product_version', '2.3.0.0'),
    ('file_version', '12.2.0.0'), ('file_version', '2.20.0.0'),
    ('file_version', 'unknown'), ('product_name', 'RealityCapture'),
    ('product_name', 'Other product')])
def test_version_mismatch_redirects(installation, monkeypatch, key, value):
    monkeypatch.setattr(rs, '_read_version', lambda path: {**VERSION, key: value})
    report = rs.validate_installation()
    assert not report['valid']
    assert 'Choose the folder' in report['diagnostics'][-1]
    with pytest.raises(rs.InstallationError, match='2.2'):
        rs.propose_repair(None, 'flightlogs.xml', [GUID])


def test_unreadable_version_is_not_guessed_from_directory(installation, monkeypatch):
    def fail(path):
        raise OSError('version denied')
    monkeypatch.setattr(rs, '_read_version', fail)
    assert not rs.inspect_installation()['ready']


def test_full_build_string_and_truncated_fixed_resource_are_reported(installation, monkeypatch):
    version = {**VERSION, 'file_version': '2.2.0.119430.RS',
               'fixed_file_version': '2.2.0.53894', 'fixed_product_version': '2.2.0.53894'}
    monkeypatch.setattr(rs, '_read_version', lambda path: version)
    report = rs.validate_installation()
    assert report['valid']
    assert report['version'] == version
    version['fixed_product_version'] = '2.1.0.53894'
    assert not rs.validate_installation()['valid']


def test_inventory_required_mapping_and_vendor_differences(installation):
    app, _, _ = installation
    path = app / 'flightlogs.xml'
    text = path.read_text().replace('desc="Example"', 'desc="vendor label"')
    path.write_text(text.replace('</FlightLogs>', block(THIRD) + '</FlightLogs>'))
    before = path.read_bytes()
    report = rs.inspect_installation()
    assert report['ready']
    row = report['managed_files']['flightlogs.xml']
    assert row['application']['sha256'] != row['repository']['sha256']
    assert row['extra_guids'] == [THIRD]
    assert row['changed_guids'] == []
    assert report['required_formats'][0]['installed_fields'][-1] == {
        'field': 'FocalLength', 'index': '13', 'format': 'value'}
    assert path.read_bytes() == before


@pytest.mark.parametrize('mutation', ['swapped', 'missing', 'reader', 'parser'])
def test_guid_presence_and_column_count_do_not_mask_wrong_contract(installation, mutation):
    app, _, _ = installation
    path = app / 'flightlogs.xml'
    text = path.read_text()
    if mutation == 'swapped':
        text = text.replace('<X index="1"', '<X index="2"').replace('<Y index="2"', '<Y index="1"')
    elif mutation == 'missing':
        text = text.replace('<FocalLength index="13" format="value"/>', '')
    elif mutation == 'reader':
        text = text.replace('RealityScan.Import.CSVFlightLog', 'other.reader')
    else:
        text = text.replace('allowedSeparators="; &tab;"', 'allowedSeparators=","')
    path.write_text(text)
    report = rs.inspect_installation()
    assert not report['ready']
    assert report['managed_files']['flightlogs.xml']['changed_guids'] == [GUID]


@pytest.mark.parametrize('kind', ['malformed', 'duplicate', 'doctype', 'wrong_root', 'missing'])
def test_invalid_managed_xml_fails_closed(installation, kind):
    app, _, _ = installation
    path = app / 'flightlogs.xml'
    if kind == 'missing':
        path.unlink()
    else:
        path.write_text({'malformed': '<FlightLogs>',
                         'duplicate': '<FlightLogs>' + block() * 2 + '</FlightLogs>',
                         'doctype': '<!DOCTYPE FlightLogs><FlightLogs></FlightLogs>',
                         'wrong_root': '<Wrong>' + block() + '</Wrong>'}[kind])
    report = rs.inspect_installation()
    assert not report['ready']
    if kind != 'missing':
        assert report['managed_files']['flightlogs.xml']['application']['sha256']
    with pytest.raises((rs.InstallationError, rs.ET.ParseError)):
        rs.propose_repair(None, 'flightlogs.xml', [GUID])


def test_missing_and_ambiguous_params_fail_closed(installation):
    _, _, params = installation
    params.write_text('<Configuration/>')
    assert not rs.inspect_installation()['ready']
    params.write_text('<Configuration>' + f'<entry key="gpsLogFileFormat" value="{GUID}"/>' * 2 + '</Configuration>')
    assert not rs.inspect_installation()['ready']
    params.unlink()
    assert not rs.inspect_installation()['ready']


def test_hash_and_version_drift_are_informational(installation, monkeypatch):
    app, _, _ = installation
    before = rs.inspect_installation()
    path = app / 'flightlogs.xml'
    path.write_bytes(path.read_bytes() + b'\n')
    monkeypatch.setattr(rs, '_read_version', lambda path: {**VERSION, 'file_version': '2.2.0.119431'})
    after = rs.inspect_installation(baseline=before)
    assert after['ready']
    assert {(row['scope'], row['field']) for row in after['drift']} == {
        ('application/flightlogs.xml', 'sha256'), ('installation', 'version')}
    before['installation']['install_dir'] += '/other'
    with pytest.raises(rs.InstallationError, match='different installation'):
        rs.inspect_installation(baseline=before)


def test_explicit_add_preserves_every_original_byte_and_unique_backup(installation):
    app, _, _ = installation
    target = missing(app)
    original = target.read_bytes()
    existing_backup = target.with_suffix('.xml.bak')
    existing_backup.write_bytes(b'previous recovery copy')
    before_files = set(app.iterdir())
    proposal = rs.propose_repair(None, 'flightlogs.xml', [GUID])
    assert set(app.iterdir()) == before_files
    assert target.read_bytes() == original
    assert proposal['actions'][0]['action'] == 'add'
    assert '+<format' in proposal['diff']
    outcome = rs.apply_repair(proposal, selected_repair_id=proposal['repair_id'])
    assert Path(outcome['backup']).read_bytes() == original
    assert existing_backup.read_bytes() == b'previous recovery copy'
    repaired = target.read_bytes()
    prefix, suffix = original.split(b'</FlightLogs>')
    assert repaired.startswith(prefix) and repaired.endswith(b'</FlightLogs>' + suffix)
    assert ff.defined_guids(str(target)) == {GUID, THIRD}
    assert not list(app.glob('*.tmp')) and not list(app.glob('*.lock'))


def test_replace_only_selected_guid_and_leave_others(installation):
    app, _, _ = installation
    path = app / 'flightlogs.xml'
    third = block(THIRD).encode()
    broken = block().replace('<X index="1"', '<X index="99"').encode()
    prefix, suffix = b'<FlightLogs>\r\n', third + b'</FlightLogs>'
    path.write_bytes(prefix + broken + suffix)
    proposal = rs.propose_repair(None, 'flightlogs.xml', [GUID])
    assert proposal['actions'][0]['action'] == 'replace'
    rs.apply_repair(proposal, selected_repair_id=proposal['repair_id'])
    assert path.read_bytes() == prefix + block().encode() + suffix


def test_self_closing_format_repair_does_not_consume_root(installation):
    app, _, _ = installation
    target = app / 'flightlogs.xml'
    target.write_text(f'<FlightLogs><format id="{GUID}"/></FlightLogs>')
    proposal = rs.propose_repair(None, 'flightlogs.xml', [GUID])
    rs.apply_repair(proposal, selected_repair_id=proposal['repair_id'])
    assert rs.inspect_installation()['ready']


@pytest.mark.parametrize('guids', [[], [THIRD], [GUID]])
def test_no_bulk_unknown_or_unnecessary_repairs(installation, guids):
    with pytest.raises(rs.InstallationError):
        rs.propose_repair(None, 'flightlogs.xml', guids)


@pytest.mark.parametrize('filename', ['../flightlogs.xml', 'RealityScan.exe', 'custom.xml'])
def test_no_unmanaged_or_traversal_targets(installation, filename):
    with pytest.raises(rs.InstallationError, match='managed XML'):
        rs.propose_repair(None, filename, [GUID])


@pytest.mark.parametrize('change', ['target', 'source', 'exe', 'content', 'path', 'selection', 'id'])
def test_stale_or_tampered_proposal_never_writes(installation, change):
    app, repo, _ = installation
    target = missing(app)
    proposal = rs.propose_repair(None, 'flightlogs.xml', [GUID])
    if change in ('target', 'source', 'exe'):
        path = {'target': target, 'source': repo / 'flightlogs.xml', 'exe': app / 'RealityScan.exe'}[change]
        path.write_bytes(path.read_bytes() + b'\n')
    elif change == 'content':
        proposal['content'] += '<!-- unapproved -->'
    elif change == 'path':
        proposal['target'] = str(repo / 'flightlogs.xml')
    elif change == 'selection':
        proposal['selected_guids'] = [THIRD]
    else:
        proposal['repair_id'] = 'forged'
    before = target.read_bytes()
    with pytest.raises(rs.InstallationError):
        rs.apply_repair(proposal, selected_repair_id=proposal['repair_id'])
    assert target.read_bytes() == before
    assert not list(app.glob('*.bak'))


def test_explicit_matching_id_required(installation):
    app, _, _ = installation
    missing(app)
    proposal = rs.propose_repair(None, 'flightlogs.xml', [GUID])
    with pytest.raises(TypeError):
        rs.apply_repair(proposal)
    with pytest.raises(rs.InstallationError, match='Explicit'):
        rs.apply_repair(proposal, selected_repair_id='')


def test_failed_atomic_replace_leaves_original_and_recovery(installation, monkeypatch):
    app, _, _ = installation
    target = missing(app)
    before = target.read_bytes()
    proposal = rs.propose_repair(None, 'flightlogs.xml', [GUID])

    def denied(*args):
        raise PermissionError('simulated protected installation')

    monkeypatch.setattr(rs.os, 'replace', denied)
    with pytest.raises(PermissionError):
        rs.apply_repair(proposal, selected_repair_id=proposal['repair_id'])
    assert target.read_bytes() == before
    assert list(app.glob('*.bak'))[0].read_bytes() == before
    assert not list(app.glob('*.tmp')) and not list(app.glob('*.lock'))


def test_existing_cooperative_lock_is_preserved(installation):
    app, _, _ = installation
    target = missing(app)
    proposal = rs.propose_repair(None, 'flightlogs.xml', [GUID])
    lock = app / 'flightlogs.xml.rs-installation.lock'
    lock.write_text('another repair')
    with pytest.raises(FileExistsError):
        rs.apply_repair(proposal, selected_repair_id=proposal['repair_id'])
    assert lock.read_text() == 'another repair'
    assert rs._file_sha(target) == proposal['before_sha256']


def test_hardlinked_target_is_refused(installation):
    app, _, _ = installation
    target = missing(app)
    os.link(target, app / 'hardlink.xml')
    with pytest.raises(rs.InstallationError, match='hardlinked'):
        rs.propose_repair(None, 'flightlogs.xml', [GUID])


def test_junction_ancestor_is_refused(installation, monkeypatch):
    app, _, _ = installation
    missing(app)
    monkeypatch.setattr(Path, 'is_junction', lambda path: path == app)
    with pytest.raises(rs.InstallationError, match='redirected paths'):
        rs.propose_repair(None, 'flightlogs.xml', [GUID])


def test_self_closing_root_requires_diagnosis(installation):
    app, _, _ = installation
    (app / 'flightlogs.xml').write_text('<FlightLogs/>')
    with pytest.raises(rs.InstallationError, match='Self-closing XML root'):
        rs.propose_repair(None, 'flightlogs.xml', [GUID])


def test_combined_add_and_replace_preserves_third_party_format(installation):
    app, repo, _ = installation
    source = repo / 'flightlogs.xml'
    source.write_text('<FlightLogs>' + block(OTHER) + block() + '</FlightLogs>')
    target = app / 'flightlogs.xml'
    foreign = block(THIRD)
    target.write_text('<FlightLogs>' + foreign + block(fields=FIELDS[:-1]) + '</FlightLogs>')
    proposal = rs.propose_repair(None, 'flightlogs.xml', [GUID, OTHER])
    assert {row['action'] for row in proposal['actions']} == {'add', 'replace'}
    rs.apply_repair(proposal, selected_repair_id=proposal['repair_id'])
    assert foreign.encode() in target.read_bytes()
    assert ff.defined_guids(str(target)) == {GUID, OTHER, THIRD}
    assert rs.inspect_installation()['ready']


def test_export_body_changes_are_detected_and_repaired(installation):
    app, _, _ = installation
    target = app / 'calibration.xml'
    target.write_text(target.read_text().replace('$(cameraCount)', 'WRONG'))
    proposal = rs.propose_repair(None, 'calibration.xml', [OTHER])
    assert proposal['actions'][0]['action'] == 'replace'
    rs.apply_repair(proposal, selected_repair_id=proposal['repair_id'])
    assert '$(cameraCount)' in target.read_text()


def test_vendor_calibration_wrapper_differs_from_repo_and_is_preserved(installation):
    app, _, _ = installation
    target = app / 'calibration.xml'
    target.write_text(target.read_text().replace('CalibrationExport', 'Calibration'))
    assert rs.inspect_installation()['ready']
    target.write_text(target.read_text().replace('$(cameraCount)', 'WRONG'))
    proposal = rs.propose_repair(None, 'calibration.xml', [OTHER])
    rs.apply_repair(proposal, selected_repair_id=proposal['repair_id'])
    assert target.read_bytes().startswith(b'<Calibration>')
    assert target.read_bytes().endswith(b'</Calibration>')
    assert rs.inspect_installation()['ready']


def test_export_body_outer_whitespace_is_part_of_contract(installation):
    app, _, _ = installation
    target = app / 'calibration.xml'
    target.write_text(target.read_text().replace('<body>', '<body>\n'))
    assert rs.inspect_installation()['managed_files']['calibration.xml']['changed_guids'] == [OTHER]


def test_source_xml_cannot_be_its_own_application_target(installation, monkeypatch):
    app, repo, _ = installation
    missing(app)
    monkeypatch.setattr(ff, 'MANAGED_FILES', (
        ('flightlogs.xml', str(app / 'flightlogs.xml')),
        ('calibration.xml', str(repo / 'calibration.xml'))))
    with pytest.raises(rs.InstallationError, match='different files'):
        rs.propose_repair(None, 'flightlogs.xml', [GUID])


def test_changed_target_during_atomic_preparation_is_refused(installation, monkeypatch):
    app, _, _ = installation
    target = missing(app)
    proposal = rs.propose_repair(None, 'flightlogs.xml', [GUID])
    original_xml = rs._xml

    def racing_read(path):
        result = original_xml(path)
        if Path(path).suffix == '.tmp':
            target.write_bytes(target.read_bytes() + b'<!-- external writer -->')
        return result

    monkeypatch.setattr(rs, '_xml', racing_read)
    with pytest.raises(rs.InstallationError, match='changed'):
        rs.apply_repair(proposal, selected_repair_id=proposal['repair_id'])
    assert target.read_bytes().endswith(b'<!-- external writer -->')
    assert not list(app.glob('*.bak'))
    assert not list(app.glob('*.tmp')) and not list(app.glob('*.lock'))


def test_cli_json_inspect_propose_apply_and_no_overwrite(installation, tmp_path, capsys):
    app, _, _ = installation
    assert rs.main(['inspect']) == 0
    assert json.loads(capsys.readouterr().out)['ready']
    target = missing(app)
    before = target.read_bytes()
    assert rs.main(['inspect']) == 2
    capsys.readouterr()
    output = tmp_path / 'proposal.json'
    args = ['propose', '--file', 'flightlogs.xml', '--guid', GUID, '--output', str(output)]
    assert rs.main(args) == 0
    proposal = json.loads(output.read_text())
    capsys.readouterr()
    assert target.read_bytes() == before
    assert rs.main(args) == 2
    capsys.readouterr()
    assert rs.main(['apply', str(output), '--repair-id', proposal['repair_id']]) == 0
    assert json.loads(capsys.readouterr().out)['backup']


def test_real_repository_default_import_mapping_is_fourteen_columns():
    # Repository-only contract check; never reads the installed application.
    for params, name, key in rs.DEFAULT_PARAMS:
        guid = ff.configured_guid(str(params), key)
        if name == 'flightlogs.xml':
            _, _, entries = rs._xml(Path(ff.REPO_FLIGHTLOGS))
            assert [field['field'] for field in entries[guid]['fields']] == list(FIELDS)
            assert ff.column_count(ff.REPO_FLIGHTLOGS, guid) == 14
