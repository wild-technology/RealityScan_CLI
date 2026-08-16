"""Guarantee the flight-log FORMAT this pipeline writes is one RealityScan
can actually read.

THE BUG THIS EXISTS TO PREVENT (twice now, both silent):

`Metadata/FlightLogParams.xml` names the parser by GUID
(`gpsLogFileFormat`). RealityScan resolves that GUID against
`flightlogs.xml` **in its own installation directory** - NOT the copy in
this repo. When the GUID is missing there, the import does not fail: it
falls back, and the columns the missing format defined are silently
DROPPED. Exit code 0, images georeferenced, priors quietly gone.

The repo's 13-column format `{B438A617}` was found missing from the
install once (testing/PRIORS_DISTORTION_TEST_PLAN.md item 1), merged in by
hand, and the note said "verify it survives app updates". It did not: on
2026-08-16 the install was stock again and
`grep -c B438A617 <install>/flightlogs.xml` returned 0. Because our first
ten columns coincide with the stock `{97F08A22}` layout, position and raw
yaw/pitch/roll still landed - so nothing looked wrong - while columns
10-12 (YawAccuracy, PitchAccuracy, RollAccuracy) were discarded on EVERY
import, leaving `ifUseOriAcc=true` with nothing to consume.

A hand-merge is not a fix; it is a fix with a half-life. This module makes
the dependency explicit and CHECKED, so a reinstall degrades into a loud
stop instead of silently unweighted priors.
"""

from __future__ import annotations

import os
import re
import shutil
import xml.etree.ElementTree as ET

# Where RealityScan looks. Ordered; first existing wins. Never hardcode a
# single path (hard rule 5) - but this one genuinely lives beside the exe.
INSTALL_DIRS = (
    r'C:\Program Files\Epic Games\RealityScan_2.2',
    r'C:\Program Files\Epic Games\RealityScan',
    r'C:\Program Files\Capturing Reality\RealityCapture',
)

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_FLIGHTLOGS = os.path.join(_REPO, 'flightlogs.xml')
REPO_CALIBRATION = os.path.join(_REPO, 'calibration.xml')

# Install-directory XMLs this repo extends. RealityScan resolves format
# GUIDs against ITS OWN copies, and reverts them on update, so every one of
# these needs the same self-healing treatment: flightlogs.xml carries the
# priors IN (position, orientation, accuracies, focal), calibration.xml
# carries the solved identity OUT (component membership + prior readback).
MANAGED_FILES: tuple[tuple[str, str], ...] = (
    ('flightlogs.xml', REPO_FLIGHTLOGS),
    ('calibration.xml', REPO_CALIBRATION),
)

_GUID_RE = re.compile(r'\{[0-9A-Fa-f-]{36}\}')

# RealityScan's flightlogs.xml uses `&tab;`, which is NOT a predefined XML
# entity, so a strict parser rejects the file outright. Substituting the
# numeric character reference lets ElementTree read it without changing
# what the separator means.
_CUSTOM_ENTITIES = (('&tab;', '&#9;'),)


def _parse(path: str) -> ET.Element:
    """Parse a RealityScan xml, tolerating its non-standard entities.

    Errors PROPAGATE. An earlier draft returned an empty set on
    ParseError, which made assert_format_installed() report a correctly
    installed format as missing - the same silent-wrong-answer failure
    mode this module exists to remove.
    """
    with open(path, 'r', encoding='utf-8-sig') as fh:
        text = fh.read()
    for bad, good in _CUSTOM_ENTITIES:
        text = text.replace(bad, good)
    return ET.fromstring(text)


class FlightLogFormatError(RuntimeError):
    """The configured flight-log format is not readable by RealityScan."""


def repo_flightlogs_hint() -> str:
    """Path to the repo's flightlogs.xml, for error messages."""
    return REPO_FLIGHTLOGS


def installed_path(filename: str, install_dir: str | None = None) -> str | None:
    """Path to an install-directory xml RealityScan actually reads."""
    candidates = [install_dir] if install_dir else list(INSTALL_DIRS)
    for d in candidates:
        if not d:
            continue
        p = os.path.join(d, filename)
        if os.path.isfile(p):
            return p
    return None


def installed_flightlogs(install_dir: str | None = None) -> str | None:
    """Path to the flightlogs.xml RealityScan actually reads, or None."""
    return installed_path('flightlogs.xml', install_dir)


def configured_guid(params_path: str) -> str | None:
    """The gpsLogFileFormat GUID named by a FlightLogParams xml."""
    root = _parse(params_path)
    for entry in root.findall('entry'):
        if entry.get('key') == 'gpsLogFileFormat':
            value = (entry.get('value') or '').strip()
            m = _GUID_RE.search(value)
            return m.group(0).upper() if m else (value or None)
    return None


def defined_guids(flightlogs_path: str) -> set[str]:
    """Every format id defined in a flightlogs.xml."""
    root = _parse(flightlogs_path)
    out = set()
    for fmt in root.findall('format'):
        fid = (fmt.get('id') or '').strip()
        if fid:
            out.add(fid.upper())
    return out


def column_count(flightlogs_path: str, guid: str) -> int | None:
    """How many columns the named format parses (max index + 1)."""
    root = _parse(flightlogs_path)
    for fmt in root.findall('format'):
        if (fmt.get('id') or '').strip().upper() != guid.upper():
            continue
        parser = fmt.find('parser')
        if parser is None:
            return None
        idx = [int(c.get('index')) for c in parser
               if c.get('index') is not None and c.get('index').isdigit()]
        return max(idx) + 1 if idx else None
    return None


def assert_format_installed(params_path: str, logger=None,
                            install_dir: str | None = None) -> str:
    """Raise unless the format named by params_path is installed.

    FAILS CLOSED. A missing format does not fail the import - it silently
    drops columns - so this must be checked BEFORE any -importFlightLog,
    not inferred from the import's exit code afterwards.
    """
    guid = configured_guid(params_path)
    if not guid:
        raise FlightLogFormatError(
            f'{params_path} names no gpsLogFileFormat GUID')

    inst = installed_flightlogs(install_dir)
    if not inst:
        raise FlightLogFormatError(
            'Could not find RealityScan\'s flightlogs.xml in any of: '
            + ', '.join(INSTALL_DIRS))

    if guid.upper() not in defined_guids(inst):
        # SELF-HEAL, then re-verify. A hand-run install step is what decayed
        # last time: the format was merged in by hand once, the note said
        # "verify it survives app updates", and the next RealityScan update
        # reverted flightlogs.xml to stock without anyone noticing. Repair
        # has to be part of the code path that needs it, not a chore.
        if logger:
            logger.warning(
                'Flight-log format %s missing from %s - installing it now '
                '(RealityScan reverts this file on update; a missing format '
                'silently DROPS columns rather than failing)', guid, inst)
        try:
            added, _ = install_repo_formats(install_dir=install_dir,
                                            logger=logger)
        except Exception as exc:                        # noqa: BLE001
            raise FlightLogFormatError(
                f'Flight-log format {guid} is missing from {inst} and could '
                f'not be installed automatically: {exc}\n'
                f'  Run: python -m modules.flightlog_format --install') from exc

        if guid.upper() not in defined_guids(inst):
            raise FlightLogFormatError(
                f'Flight-log format {guid} is NOT defined in {inst}, and '
                f'auto-install added {added} format(s) without providing it.\n'
                f'  RealityScan resolves gpsLogFileFormat against its INSTALL\n'
                f'  directory, not this repo. A missing format does not error -\n'
                f'  it falls back and SILENTLY DROPS the columns that format\n'
                f'  defined (orientation accuracies were lost this way on\n'
                f'  every import before 2026-08-16).\n'
                f'  Check that {repo_flightlogs_hint()} defines {guid}.')
        if logger:
            logger.info('Installed flight-log format %s into %s', guid, inst)

    n = column_count(inst, guid)
    if logger:
        logger.info('Flight-log format %s installed in %s (%s columns)',
                    guid, inst, n if n is not None else '?')
    return guid


def install_all_managed(install_dir: str | None = None,
                        logger=None) -> dict[str, int]:
    """Install every repo format into every managed install-directory xml.

    Returns {filename: formats_added}. A managed file that RealityScan does
    not ship is skipped rather than fatal - only the ones actually resolved
    against matter, and the per-import guard catches a genuinely missing
    format at the point of use.
    """
    out: dict[str, int] = {}
    for filename, repo_copy in MANAGED_FILES:
        if not os.path.isfile(repo_copy):
            continue
        if not installed_path(filename, install_dir):
            if logger:
                logger.warning('No installed %s to extend - skipping', filename)
            continue
        added, _ = install_repo_formats(install_dir=install_dir,
                                        repo_flightlogs=repo_copy,
                                        logger=logger, filename=filename)
        out[filename] = added
    return out


def install_repo_formats(install_dir: str | None = None,
                         repo_flightlogs: str = REPO_FLIGHTLOGS,
                         logger=None,
                         filename: str = 'flightlogs.xml') -> tuple[int, str]:
    """Merge formats defined in the repo copy into the installed copy.

    Only ADDS formats whose GUID is absent; never rewrites or removes a
    stock one. Backs the install file up first.
    """
    inst = installed_path(filename, install_dir)
    if not inst:
        raise FlightLogFormatError(f'No installed {filename} found')

    have = defined_guids(inst)
    repo_root = _parse(repo_flightlogs)
    missing = [(f.get('id') or '').strip() for f in repo_root.findall('format')
               if (f.get('id') or '').strip().upper() not in have]
    if not missing:
        return 0, inst

    backup = inst + '.bak'
    if not os.path.exists(backup):
        shutil.copy2(inst, backup)

    # TEXT-level splice, deliberately not an ElementTree round-trip: writing
    # the tree back would reindent the whole stock file and turn its `&tab;`
    # into `&#9;`. Only the appended blocks should differ.
    with open(repo_flightlogs, 'r', encoding='utf-8-sig') as fh:
        repo_text = fh.read()
    with open(inst, 'r', encoding='utf-8-sig') as fh:
        inst_text = fh.read()

    blocks = []
    for guid in missing:
        m = re.search(
            r'([ \t]*<format\s+id="' + re.escape(guid) + r'".*?</format>)',
            repo_text, re.DOTALL | re.IGNORECASE)
        if not m:
            raise FlightLogFormatError(
                f'{guid} is declared missing but no <format> block for it '
                f'could be extracted from {repo_flightlogs}')
        blocks.append(m.group(1).rstrip())

    # Root tag differs per managed file (<FlightLogs>, <CalibrationExport>,
    # ...), so derive it from the install copy rather than hardcoding one.
    root_tag = _parse(inst).tag
    close = inst_text.rfind(f'</{root_tag}>')
    if close < 0:
        raise FlightLogFormatError(
            f'{inst} has no </{root_tag}> close tag to splice before')
    addition = ('\n' + '\n\n'.join(blocks) + '\n\n')
    new_text = inst_text[:close] + addition + inst_text[close:]
    with open(inst, 'w', encoding='utf-8', newline='') as fh:
        fh.write(new_text)

    if logger:
        logger.info('Installed %d flight-log format(s) into %s (backup: %s)',
                    len(blocks), inst, backup)
    return len(blocks), inst


if __name__ == '__main__':
    import argparse
    import logging

    logging.basicConfig(level=logging.INFO, format='%(message)s')
    log = logging.getLogger('flightlog_format')

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--install', action='store_true',
                    help='merge repo formats into the RealityScan install')
    ap.add_argument('--check', metavar='PARAMS_XML',
                    help='assert the format named by this params xml is installed')
    args = ap.parse_args()

    if args.install:
        n, path = install_repo_formats(logger=log)
        log.info('%d format(s) added to %s', n, path)
    if args.check:
        guid = assert_format_installed(args.check, logger=log)
        log.info('OK: %s is installed', guid)
    if not args.install and not args.check:
        inst = installed_flightlogs()
        log.info('installed flightlogs.xml: %s', inst)
        if inst:
            for g in sorted(defined_guids(inst)):
                log.info('  %s  (%s columns)', g, column_count(inst, g))
