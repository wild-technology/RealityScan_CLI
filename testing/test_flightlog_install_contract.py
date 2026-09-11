"""Strict import/export guards: fixture XML only, no installed software writes."""
from pathlib import Path

import pytest

from modules import flightlog_format as ff
from modules import rs_installation as installation


GUID = '{11111111-2222-3333-4444-555555555555}'
FLIGHT = (f'<FlightLogs><format id="{GUID}" desc="label" reader="reader">'
          '<parser allowedSeparators="; &tab;"><Image index="0" format="name.ext"/>'
          '<X index="1" format="value"/></parser></format></FlightLogs>')
CALIBRATION = (f'<CalibrationExport><format id="{GUID}" desc="label">'
               '<body>one\n two</body></format></CalibrationExport>')


@pytest.fixture
def selected(tmp_path, monkeypatch):
    for key in ('RS_EXECUTABLE', 'RS_REQUIRE_INSTALL_CONTRACT', 'RS_NO_SETTINGS_INHERITANCE'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('RS_NO_SETTINGS_INHERITANCE', '1')
    app, repo = tmp_path / 'selected app', tmp_path / 'catalog'
    app.mkdir()
    repo.mkdir()
    (app / 'RealityScan.exe').write_bytes(b'not an executable; version reader mocked')
    monkeypatch.setattr(installation, '_read_version', lambda path: {
        'product_name': 'RealityScan', 'file_version': '2.2.0.119430',
        'product_version': '2.2.0.119430'})
    monkeypatch.setenv('RS_EXECUTABLE', str(app / 'RealityScan.exe'))
    params = {}
    for filename, text, key in (
        ('flightlogs.xml', FLIGHT, ff.FLIGHTLOG_FORMAT_KEY),
        ('calibration.xml', CALIBRATION, ff.CALIBRATION_EXPORT_FORMAT_KEY),
    ):
        for folder in (app, repo):
            (folder / filename).write_text(text, encoding='utf-8')
        path = repo / (filename + '.params')
        path.write_text(f'<Configuration><entry key="{key}" value="{GUID}"/></Configuration>')
        params[filename] = path
    monkeypatch.setattr(ff, 'MANAGED_FILES', tuple((n, str(repo / n)) for n in params))
    monkeypatch.setattr(installation, 'DEFAULT_PARAMS', (
        (params['flightlogs.xml'], 'flightlogs.xml', ff.FLIGHTLOG_FORMAT_KEY),
        (params['calibration.xml'], 'calibration.xml', ff.CALIBRATION_EXPORT_FORMAT_KEY)))
    monkeypatch.setattr(installation, 'DEFAULT_INSTALL_DIR', str(app))
    return app, repo, params


def snapshot(folder):
    return {str(p.relative_to(folder)): p.read_bytes() for p in folder.rglob('*') if p.is_file()}


def guard(filename):
    return (ff.assert_format_installed if filename == 'flightlogs.xml'
            else ff.assert_calibration_format_installed)


@pytest.mark.parametrize('filename', ['flightlogs.xml', 'calibration.xml'])
def test_matching_semantics_allow_cosmetic_labels_and_wrappers(selected, filename):
    app, _, params = selected
    target = app / filename
    text = target.read_text().replace('desc="label"', 'desc="new label" descID="99"')
    if filename == 'calibration.xml':
        text = text.replace('CalibrationExport', 'Calibration')
    else:
        text = text.replace('><', '>\n    <').replace('&tab;', '&#9;')
    target.write_text(text)
    before = snapshot(app)
    assert guard(filename)(params[filename]) == GUID
    assert snapshot(app) == before


@pytest.mark.parametrize('filename,old,new', [
    ('flightlogs.xml', '<X ', '<Y '),
    ('flightlogs.xml', 'index="1"', 'index="0"'),
    ('flightlogs.xml', 'reader="reader"', 'reader="different"'),
    ('flightlogs.xml', 'allowedSeparators="; &tab;"', 'allowedSeparators=","'),
    ('calibration.xml', 'one\n two', 'one\ntwo'),
])
def test_same_guid_drift_has_concrete_selected_repair_without_writes(selected, filename, old, new):
    app, _, params = selected
    target = app / filename
    target.write_text(target.read_text().replace(old, new))
    before = snapshot(app)
    with pytest.raises(ff.FlightLogFormatError, match='missing or differs') as caught:
        guard(filename)(params[filename])
    proposal = caught.value.repair_proposal
    assert proposal['selected_guids'] == [GUID]
    assert proposal['target'] == str(target)
    assert proposal['actions'][0]['action'] == 'replace'
    assert proposal['diff'] and proposal['repair_id']
    assert snapshot(app) == before


@pytest.mark.parametrize('filename', ['flightlogs.xml', 'calibration.xml'])
def test_missing_guid_proposes_add_never_autoheals(selected, filename):
    app, _, params = selected
    root = 'FlightLogs' if filename == 'flightlogs.xml' else 'Calibration'
    (app / filename).write_text(f'<{root}></{root}>')
    before = snapshot(app)
    with pytest.raises(ff.FlightLogFormatError) as caught:
        guard(filename)(params[filename])
    assert caught.value.repair_proposal['actions'][0]['action'] == 'add'
    assert snapshot(app) == before


@pytest.mark.parametrize('damage', ['duplicate_guid', 'duplicate_params', 'missing_params',
                                   'decorated_guid', 'unknown_guid', 'malformed', 'dtd',
                                   'wrong_root', 'wrong_params_root', 'missing_xml', 'bad_repo'])
def test_unverifiable_contract_refuses_without_implicit_repair(selected, damage):
    app, repo, params = selected
    target = app / 'flightlogs.xml'
    param = params['flightlogs.xml']
    if damage == 'duplicate_guid':
        text = target.read_text()
        block = text[text.index('<format '):text.index('</format>') + len('</format>')]
        target.write_text(text.replace('</FlightLogs>', block + '</FlightLogs>'))
    elif damage == 'duplicate_params':
        param.write_text(param.read_text().replace('</Configuration>',
            f'<entry key="{ff.FLIGHTLOG_FORMAT_KEY}" value="{GUID}"/></Configuration>'))
    elif damage == 'missing_params':
        param.write_text('<Configuration/>')
    elif damage in ('decorated_guid', 'unknown_guid'):
        param.write_text(param.read_text().replace(GUID, 'prefix ' + GUID if damage == 'decorated_guid'
                                                  else '{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}'))
    elif damage == 'malformed':
        target.write_text('<FlightLogs>')
    elif damage == 'dtd':
        param.write_text('<!DOCTYPE Configuration []>' + param.read_text())
    elif damage == 'wrong_root':
        target.write_text(target.read_text().replace('FlightLogs', 'Anything'))
    elif damage == 'wrong_params_root':
        param.write_text(param.read_text().replace('Configuration', 'Anything'))
    elif damage == 'missing_xml':
        target.unlink()
    else:
        (repo / 'flightlogs.xml').write_text('<FlightLogs>')
    before = snapshot(app)
    with pytest.raises(ff.FlightLogFormatError, match='No files were changed') as caught:
        ff.assert_format_installed(param)
    assert caught.value.repair_proposal is None
    assert snapshot(app) == before


@pytest.mark.parametrize('flag', ['RS_NO_SETTINGS_INHERITANCE', 'RS_REQUIRE_INSTALL_CONTRACT'])
def test_either_flag_blocks_all_legacy_writes(selected, monkeypatch, flag):
    app, _, _ = selected
    monkeypatch.delenv('RS_NO_SETTINGS_INHERITANCE', raising=False)
    monkeypatch.setenv(flag, '1')
    before = snapshot(app)
    assert ff.install_all_managed() == {'flightlogs.xml': 0, 'calibration.xml': 0}
    with pytest.raises(ff.FlightLogFormatError, match='propose_repair'):
        ff.install_repo_formats()
    assert snapshot(app) == before
    (app / 'calibration.xml').write_text('<Calibration></Calibration>')
    before = snapshot(app)
    with pytest.raises(ff.FlightLogFormatError) as caught:
        ff.install_all_managed()
    assert caught.value.repair_proposal['filename'] == 'calibration.xml'
    assert snapshot(app) == before


def test_explicit_selection_never_falls_back_when_xml_missing(selected, monkeypatch):
    app, repo, _ = selected
    monkeypatch.setattr(ff, 'INSTALL_DIRS', (str(repo),))
    assert ff.installed_path('flightlogs.xml') == str(app / 'flightlogs.xml')
    (app / 'flightlogs.xml').unlink()
    assert ff.installed_path('flightlogs.xml') is None
    # Explicit audit selection remains independent of execution environment.
    assert ff.installed_path('flightlogs.xml', str(repo)) == str(repo / 'flightlogs.xml')


@pytest.mark.parametrize('bad', ['', 'relative/RealityScan.exe', 'absent', 'wrong_name', 'wrong_version'])
def test_invalid_explicit_executable_refuses_fallback(selected, monkeypatch, bad):
    app, repo, _ = selected
    monkeypatch.setattr(ff, 'INSTALL_DIRS', (str(repo),))
    if bad == 'wrong_version':
        monkeypatch.setattr(installation, '_read_version', lambda p: {
            'product_name': 'RealityScan', 'file_version': '2.1.0.1', 'product_version': '2.1.0.1'})
    else:
        value = str(app / 'missing' / 'RealityScan.exe') if bad == 'absent' else bad
        if bad == 'wrong_name':
            path = app / 'other.exe'
            path.write_bytes(b'fixture')
            value = str(path)
        monkeypatch.setenv('RS_EXECUTABLE', value)
    with pytest.raises(ff.FlightLogFormatError):
        ff.installed_path('flightlogs.xml')


def test_strict_guard_rejects_conflicting_explicit_directory(selected):
    _, repo, params = selected
    with pytest.raises(ff.FlightLogFormatError, match='conflicts'):
        ff.assert_format_installed(params['flightlogs.xml'], install_dir=str(repo))


def test_strict_without_explicit_exe_uses_only_validated_default(selected, monkeypatch):
    app, repo, params = selected
    monkeypatch.delenv('RS_EXECUTABLE')
    monkeypatch.setattr(ff, 'INSTALL_DIRS', (str(repo),))
    assert ff.assert_format_installed(params['flightlogs.xml']) == GUID
    assert ff.installed_path('flightlogs.xml') == str(app / 'flightlogs.xml')
    (app / 'RealityScan.exe').unlink()
    with pytest.raises(ff.FlightLogFormatError):
        ff.installed_path('flightlogs.xml')


def test_disabled_strict_flags_preserve_legacy_autoheal(selected, monkeypatch):
    app, repo, params = selected
    monkeypatch.setenv('RS_NO_SETTINGS_INHERITANCE', '0')
    monkeypatch.setenv('RS_REQUIRE_INSTALL_CONTRACT', 'false')
    (app / 'flightlogs.xml').write_text('<FlightLogs></FlightLogs>')
    # Legacy helper's default argument names the production catalog, so supply
    # the fixture catalog explicitly when exercising its additive behavior.
    count, path = ff.install_repo_formats(repo_flightlogs=str(repo / 'flightlogs.xml'))
    assert count == 1
    assert Path(path + '.bak').exists()
    assert ff.assert_format_installed(params['flightlogs.xml']) == GUID


@pytest.mark.parametrize('flags', [('1', '0'), ('0', '1'), ('0', 'unexpected')])
def test_one_disabled_flag_cannot_enable_implicit_writes(selected, monkeypatch, flags):
    app, _, params = selected
    monkeypatch.setenv('RS_NO_SETTINGS_INHERITANCE', flags[0])
    monkeypatch.setenv('RS_REQUIRE_INSTALL_CONTRACT', flags[1])
    (app / 'flightlogs.xml').write_text('<FlightLogs></FlightLogs>')
    before = snapshot(app)
    with pytest.raises(ff.FlightLogFormatError) as caught:
        ff.assert_format_installed(params['flightlogs.xml'])
    assert caught.value.repair_proposal['selected_guids'] == [GUID]
    assert snapshot(app) == before


def test_unrelated_definitions_and_guid_case_do_not_change_selected_contract(selected):
    app, repo, params = selected
    other = '{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}'
    for folder, reader in ((app, 'vendor'), (repo, 'repo')):
        path = folder / 'flightlogs.xml'
        path.write_text(path.read_text().replace('</FlightLogs>',
            f'<format id="{other}" reader="{reader}"/></FlightLogs>'))
    target = app / 'flightlogs.xml'
    # Case normalization applies to format identity, not parser attributes.
    replacement = '{ABCDEF12-2222-3333-4444-555555555555}'
    target.write_text(target.read_text().replace(GUID, replacement.lower()))
    source = repo / 'flightlogs.xml'
    source.write_text(source.read_text().replace(GUID, replacement))
    param = params['flightlogs.xml']
    param.write_text(param.read_text().replace(GUID, replacement.lower()))
    before = snapshot(app)
    assert ff.assert_format_installed(param) == replacement
    assert snapshot(app) == before
