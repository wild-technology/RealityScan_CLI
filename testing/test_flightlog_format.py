"""The flight-log FORMAT must be registered where RealityScan looks.

Every test here traces to one incident: the custom format GUID named by
FlightLogParams.xml was absent from the RealityScan INSTALL's
flightlogs.xml, so the import fell back to a stock parser and silently
dropped the trailing columns. It was found once, hand-patched, and lost
again on the next app update. A silent drop cannot be detected after the
fact, so it is asserted before the import.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import flightlog_format as ff       # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
METADATA = os.path.join(REPO, 'modules', 'realityscan_interface',
                        'RS_CLI', 'Metadata')

# A flightlogs.xml uses `&tab;`, which is NOT a predefined XML entity.
_TAB_XML = '''<FlightLogs>
    <format id="{AAAAAAAA-0000-0000-0000-000000000001}" desc="t" reader="RealityScan.Import.CSVFlightLog">
        <parser allowedSeparators=",; &tab;" comment="#" showIgnoreFirstline="true" qualifiers="&quot;optional">
            <Image index="0" format="name.ext"/>
            <X index="1" format="value"/>
            <Y index="2" format="value"/>
            <FocalLength index="3" format="value"/>
        </parser>
    </format>
</FlightLogs>
'''


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding='utf-8')
    return str(p)


def test_parses_files_containing_the_tab_entity(tmp_path):
    """`&tab;` made a strict parser raise. The first draft SWALLOWED that
    and returned an empty set, which reports a correctly installed format
    as missing - the same silent-wrong-answer this module exists to kill."""
    p = _write(tmp_path, 'flightlogs.xml', _TAB_XML)
    assert '{AAAAAAAA-0000-0000-0000-000000000001}' in ff.defined_guids(p)
    assert ff.column_count(p, '{AAAAAAAA-0000-0000-0000-000000000001}') == 4


def test_parse_errors_propagate_rather_than_reading_as_empty(tmp_path):
    p = _write(tmp_path, 'flightlogs.xml', '<FlightLogs><format id=')
    with pytest.raises(Exception):
        ff.defined_guids(p)


def test_missing_format_is_refused_not_warned(tmp_path):
    """The whole point: absent GUID must raise BEFORE any import."""
    logs = _write(tmp_path, 'flightlogs.xml', _TAB_XML)
    params = _write(tmp_path, 'p.xml',
                    '<Configuration><entry key="gpsLogFileFormat" '
                    'value="{BBBBBBBB-0000-0000-0000-000000000002}"/></Configuration>')
    os.makedirs(tmp_path / 'inst', exist_ok=True)
    import shutil
    shutil.copy(logs, tmp_path / 'inst' / 'flightlogs.xml')
    with pytest.raises(ff.FlightLogFormatError, match='NOT defined'):
        ff.assert_format_installed(params, install_dir=str(tmp_path / 'inst'))


def test_guard_self_heals_a_reverted_install(tmp_path):
    """A RealityScan update reverts flightlogs.xml to stock. The guard must
    REPAIR it, not just complain: the previous fix was a hand-run merge with
    a note saying 'verify it survives app updates', and it did not."""
    import shutil
    inst_dir = tmp_path / 'inst'
    os.makedirs(inst_dir, exist_ok=True)
    # Stock: valid file, but WITHOUT any of our formats.
    shutil.copy(_write(tmp_path, 'stock.xml', _TAB_XML),
                inst_dir / 'flightlogs.xml')
    params = os.path.join(METADATA, 'FlightLogParams.xml')
    guid = ff.configured_guid(params)
    assert guid.upper() not in ff.defined_guids(str(inst_dir / 'flightlogs.xml'))

    ff.assert_format_installed(params, install_dir=str(inst_dir))

    after = ff.defined_guids(str(inst_dir / 'flightlogs.xml'))
    assert guid.upper() in after, 'guard must install the missing format'
    assert ff.column_count(str(inst_dir / 'flightlogs.xml'), guid) == 14


def test_present_format_passes(tmp_path):
    logs = _write(tmp_path, 'flightlogs.xml', _TAB_XML)
    params = _write(tmp_path, 'p.xml',
                    '<Configuration><entry key="gpsLogFileFormat" '
                    'value="{AAAAAAAA-0000-0000-0000-000000000001}"/></Configuration>')
    os.makedirs(tmp_path / 'inst', exist_ok=True)
    import shutil
    shutil.copy(logs, tmp_path / 'inst' / 'flightlogs.xml')
    guid = ff.assert_format_installed(params, install_dir=str(tmp_path / 'inst'))
    assert guid == '{AAAAAAAA-0000-0000-0000-000000000001}'


def test_shipped_params_name_a_14_column_format():
    """FlightLogParams must name the format the writer actually emits.
    A 13-column log read by a 14-column parser (or the reverse) is exactly
    the mismatch that loses columns without erroring."""
    for name in ('FlightLogParams.xml', 'FlightLogParamsLocal.xml'):
        guid = ff.configured_guid(os.path.join(METADATA, name))
        assert guid, f'{name} names no gpsLogFileFormat'
        assert ff.column_count(ff.REPO_FLIGHTLOGS, guid) == 14, name


def test_repo_format_defines_focal_length():
    """FocalLength is the ONLY route this prior has to RealityScan: no CLI
    command sets focal, the WCA units carry no EXIF focal tag, and sidecars
    are forbidden."""
    with open(ff.REPO_FLIGHTLOGS, encoding='utf-8') as fh:
        text = fh.read()
    guid = ff.configured_guid(os.path.join(METADATA, 'FlightLogParams.xml'))
    block = text[text.index(guid):]
    block = block[:block.index('</format>')]
    assert '<FocalLength index="13"' in block


def test_installing_is_idempotent_and_additive(tmp_path):
    """Re-running --install must not duplicate or rewrite stock formats."""
    import shutil
    inst_dir = tmp_path / 'inst'
    os.makedirs(inst_dir, exist_ok=True)
    stock = _write(tmp_path, 'stock.xml', _TAB_XML)
    shutil.copy(stock, inst_dir / 'flightlogs.xml')
    before = ff.defined_guids(str(inst_dir / 'flightlogs.xml'))

    n1, _ = ff.install_repo_formats(install_dir=str(inst_dir))
    after1 = ff.defined_guids(str(inst_dir / 'flightlogs.xml'))
    n2, _ = ff.install_repo_formats(install_dir=str(inst_dir))
    after2 = ff.defined_guids(str(inst_dir / 'flightlogs.xml'))

    assert n1 > 0 and n2 == 0, 'second install should add nothing'
    assert after1 == after2
    assert before <= after1, 'stock formats must survive'
