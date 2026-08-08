"""Shared flight-log discovery.

The pipeline writes flight logs under several names depending on which
stage produced them:

- ``flight_log_<zone>_UTM.txt``          georeference module (zone = UTM zone)
- ``flight_log_<dive>_<zone>_UTM.txt``   geoall.py (multi-dive)
- ``flight_log<suffix>_UTM.txt``         per-zone copies from Batch Directory
  (suffix may be empty, giving ``flight_log_UTM.txt``)
- ``flight_log.txt``                     legacy runs

Every consumer that needs to locate a flight log on disk must go through
:func:`find_flight_log` so the naming conventions stay in one place.
"""

from __future__ import annotations

import glob
import os
import re

# MGRS latitude bands C..M lie south of the equator, N..X north (I and O
# are never used). The band letter rides along in the flight-log filename
# (utm.from_latlon's zone letter), so the EPSG code can be derived instead
# of hand-edited per cruise in FlightLogParams.xml.
_SOUTH_BANDS = set('CDEFGHJKLM')
_NORTH_BANDS = set('NPQRSTUVWX')

_ZONE_IN_NAME = re.compile(r'_(\d{1,2})([C-HJ-NP-X])_UTM\.txt$', re.IGNORECASE)


def assert_one_zone(paths, context: str) -> tuple[int, str] | None:
    """The single UTM zone shared by every flight log in ``paths``.

    Returns the (zone, band) they agree on, or None when they all carry no
    zone tag (a local-frame campaign). Raises ValueError when they
    DISAGREE - including a tagged/untagged mix, which is a frame
    disagreement, not just a zone one.

    Determinism is not correctness: picking "the first" log out of a
    mixed-zone directory georeferences the other cruise's imagery ~2,000 km
    away, silently, under a CRS derived from the wrong filename
    (audit 2026-08-07).
    """
    seen: dict[tuple[int, str] | None, list[str]] = {}
    for path in paths:
        seen.setdefault(utm_zone_from_flight_log_name(path), []).append(path)
    if len(seen) <= 1:
        return next(iter(seen), None) if seen else None
    detail = '; '.join(
        f'{"no zone tag" if z is None else str(z[0]) + z[1]}: '
        + ', '.join(os.path.basename(p) for p in sorted(files))
        for z, files in sorted(seen.items(),
                               key=lambda kv: (kv[0] is not None, kv[0])))
    raise ValueError(
        f'{context} holds flight logs of DISAGREEING coordinate frames '
        f'({detail}). Refusing to pick one: {_FRAME_INCIDENT}. Keep exactly '
        'one cruise/zone per directory, or pass the intended log explicitly.')


def find_flight_log(*directories: str | None) -> str | None:
    """Return the first flight log found across the candidate directories.

    All directories are searched for current-format ``flight_log*_UTM.txt``
    logs before any is searched for a legacy ``flight_log.txt``, so a
    georeferenced log always wins over a stale legacy one. Multiple UTM
    logs in one directory resolve to the lexicographically first for
    determinism - but only after :func:`assert_one_zone` has verified they
    all name the SAME zone; disagreement raises ValueError rather than
    silently choosing. Returns ``None`` when nothing matches.
    """
    valid = [d for d in directories if d and os.path.isdir(d)]

    for directory in valid:
        matches = sorted(glob.glob(os.path.join(directory, 'flight_log*_UTM.txt')))
        if matches:
            assert_one_zone(matches, directory)
            return matches[0]

    for directory in valid:
        legacy = os.path.join(directory, 'flight_log.txt')
        if os.path.isfile(legacy):
            return legacy

    return None


def utm_zone_from_flight_log_name(path: str) -> tuple[int, str] | None:
    """(zone number, band letter) parsed from a flight-log filename like
    ``flight_log_53N_UTM.txt`` / ``flight_log_NA167_H2075_53N_UTM.txt``,
    or None when the name carries no zone tag."""
    match = _ZONE_IN_NAME.search(os.path.basename(path))
    if not match:
        return None
    zone = int(match.group(1))
    band = match.group(2).upper()
    if not 1 <= zone <= 60 or band not in _SOUTH_BANDS | _NORTH_BANDS:
        return None
    return zone, band


def validate_utm_zone(zone, band) -> tuple[int, str]:
    """(zone, BAND) after checking both are real, or ValueError.

    utm_zone_from_flight_log_name validates what it PARSES; the writers
    below took whatever they were handed, so a typo produced a
    plausible-looking but nonexistent CRS with exit code 0 - and an
    unknown band silently fell into the NORTHERN branch, turning a
    southern-hemisphere typo into a northern EPSG (audit 2026-08-07).
    """
    try:
        zone_int = int(zone)
    except (TypeError, ValueError):
        raise ValueError(f'invalid UTM zone {zone!r} - must be an '
                         'integer 1-60') from None
    band_up = str(band).upper()
    if not 1 <= zone_int <= 60 or band_up not in _SOUTH_BANDS | _NORTH_BANDS:
        raise ValueError(
            f'invalid UTM zone {zone_int}{band_up} - zone must be 1-60 and '
            'the MGRS latitude band one of C-X excluding I and O. Take both '
            'from the flight log filename via utm_zone_from_flight_log_name, '
            'never from a hand-edited template.')
    return zone_int, band_up


def crs_for_flight_log(path: str | None) -> str | None:
    """``'EPSG:32654'`` for a zone-tagged flight log, else None.

    The publish path needs this: georeferenced OBJ/FBX exports carry raw
    UTM metres (ModelExportParamsOBJ_NiraParts sets
    MvsExportIsGeoreferenced with scale 1.0 and no offset), and uploading
    them without a CRS puts the asset in the wrong part of the world
    (audit 2026-08-07).
    """
    if not path:
        return None
    zone_band = utm_zone_from_flight_log_name(path)
    if zone_band is None:
        return None
    return f'EPSG:{epsg_for_utm_zone(*zone_band)}'


def epsg_for_utm_zone(zone: int, band: str) -> int:
    """EPSG code for a WGS84 UTM zone: 326xx north, 327xx south."""
    zone, band = validate_utm_zone(zone, band)
    return (32700 if band in _SOUTH_BANDS else 32600) + zone


# The local-Euclidean coordinate-system pair RealityScan expects for
# COLMAP-prior campaigns (validated on ON2026, FINDINGS C-20260730-05).
_LOCAL_PROJ = '+proj=geocent +ellps=WGS84 +no_defs'
_LOCAL_TYPE = 'local:1 - Euclidean'

_FRAME_INCIDENT = (
    "a frame mismatch imports the trajectory silently in the wrong frame "
    "(2026-08-07 incident: the shared FlightLogParams template still "
    "carried ON2026's local frame and a UTM 57L log imported through it "
    "with exit code 0 and no warning)")


def params_template_frame(template_path: str) -> str:
    """Coordinate frame a FlightLogParams XML declares:
    ``'utm'`` | ``'local_euclidean'`` | ``'unknown'``."""
    # Named error instead of a raw FileNotFoundError (missing file) or
    # PermissionError (a DIRECTORY passed as the template) out of open():
    # this is reached from both public entry points, so the operator has
    # to be told WHICH file the pipeline wanted (audit 2026-08-07).
    if not os.path.isfile(template_path):
        raise FileNotFoundError(
            f'FlightLogParams template not found (or is not a file): '
            f'{template_path!r}. Expected one of '
            'Metadata/FlightLogParams.xml (UTM cruises) or '
            'Metadata/FlightLogParamsLocal.xml (local-frame campaigns).')
    with open(template_path, encoding='utf-8') as f:
        content = f.read()
    proj_m = re.search(
        r'<entry key="CoordinateSystemFlightLog" value="([^"]*)"', content)
    type_m = re.search(
        r'<entry key="CoordinateSystemFlightLogType" value="([^"]*)"', content)
    proj = proj_m.group(1) if proj_m else ''
    crs_type = (type_m.group(1) if type_m else '').lower()
    if '+proj=geocent' in proj or crs_type.startswith('local:'):
        return 'local_euclidean'
    if '+proj=utm' in proj or crs_type.startswith('epsg:'):
        return 'utm'
    return 'unknown'


def ensure_frame_match(flight_log_path: str, template_path: str) -> str:
    """Frame the flight-log filename implies (``'utm'`` when it carries a
    zone tag like ``_57L_UTM.txt``, ``'local_euclidean'`` otherwise), after
    verifying the params template does not declare the OPPOSITE frame.

    Raises ValueError on mismatch instead of importing: a frame mismatch
    imports the trajectory silently in the wrong frame (2026-08-07
    incident, see _FRAME_INCIDENT: UTM 57L log through the local template
    imported in the wrong frame with exit code 0 and no warning;
    the frame's effect on that fixture's registration was later isolated
    as NOT the dominant suppressor - backlog B7 - but a silently
    mis-framed trajectory is wrong regardless of what it costs).
    """
    expected = ('utm' if utm_zone_from_flight_log_name(flight_log_path)
                else 'local_euclidean')
    declared = params_template_frame(template_path)
    if declared not in ('unknown', expected):
        remedy = (
            'Use Metadata/FlightLogParams.xml for UTM cruises and '
            'Metadata/FlightLogParamsLocal.xml for local-frame campaigns.')
        if expected == 'local_euclidean':
            # The untagged name is what implied 'local' - if this log is
            # really from a UTM cruise (legacy flight_log.txt), the fix is
            # the zone tag, not the local template.
            remedy += (
                ' If this log actually IS from a UTM cruise, rename it to '
                'carry its zone tag (e.g. flight_log_53N_UTM.txt) so the '
                'zone can be derived from the filename - proceeding with '
                "the template's placeholder zone is the NA173 silent "
                'mis-import.')
        raise ValueError(
            f'Flight log "{os.path.basename(flight_log_path)}" implies a '
            f'{expected} frame but the params template {template_path} '
            f'declares {declared}. Refusing to import: {_FRAME_INCIDENT}. '
            f'{remedy}')
    return expected


def write_flight_log_params(template_path: str, output_path: str,
                            zone: int | None = None, band: str | None = None,
                            frame: str = 'utm') -> str:
    """Copy the FlightLogParams template with its coordinate-system pair
    rewritten for the requested frame. Returns output_path.

    ``frame='utm'`` (default) requires ``zone`` and ``band`` and rewrites
    the pair for that WGS84 UTM zone, exactly as before the frame
    parameter existed. ``frame='local_euclidean'`` writes the
    geocent / ``local:1 - Euclidean`` pair (COLMAP-prior campaigns such as
    ON2026) and ignores ``zone``/``band``.

    Two distinct hazards, both hit live, motivate this function:

    - Wrong ZONE: RealityScan mis-imports every trajectory silently when
      the params XML declares the wrong zone (HANDOFF.md: NA173 logs were
      zone 57S while the template still said 4N) - so the zone must come
      from the flight log itself, never a hand-edited template.
    - Wrong FRAME (incident 2026-08-07): commit 902fcf7 promoted ON2026's
      hand-made local-frame file over the shared template, and a UTM 57L
      import went through geocent/local:1 silently with exit code 0
      and no warning. A template that declares the opposite frame from
      the one requested is therefore refused outright (ValueError); pick
      FlightLogParams.xml (UTM) or FlightLogParamsLocal.xml (local).
    """
    if frame not in ('utm', 'local_euclidean'):
        raise ValueError(
            f"frame must be 'utm' or 'local_euclidean', got {frame!r}")
    declared = params_template_frame(template_path)
    if declared not in ('unknown', frame):
        raise ValueError(
            f'FlightLogParams template {template_path} declares a '
            f'{declared} coordinate system but frame={frame!r} was '
            f'requested. Refusing to write params: {_FRAME_INCIDENT}. '
            'Use Metadata/FlightLogParams.xml for UTM cruises and '
            'Metadata/FlightLogParamsLocal.xml for local-frame campaigns.')

    if frame == 'utm':
        if zone is None or band is None:
            raise ValueError("frame='utm' requires zone and band "
                             '(parse them from the flight-log filename via '
                             'utm_zone_from_flight_log_name)')
        zone, band = validate_utm_zone(zone, band)
        epsg = epsg_for_utm_zone(zone, band)
        south = ' +south' if band in _SOUTH_BANDS else ''
        hemisphere = 'S' if south else 'N'
        proj = f'+proj=utm +zone={zone}{south} +datum=WGS84 +units=m +no_defs'
        crs_type = f'epsg:{epsg} - WGS 84 / UTM zone {zone}{hemisphere}'
    else:
        proj = _LOCAL_PROJ
        crs_type = _LOCAL_TYPE

    with open(template_path, encoding='utf-8') as f:
        content = f.read()
    content = re.sub(
        r'(<entry key="CoordinateSystemFlightLog" value=")[^"]*("/>)',
        lambda m: m.group(1) + proj + m.group(2), content)
    content = re.sub(
        r'(<entry key="CoordinateSystemFlightLogType" value=")[^"]*("/>)',
        lambda m: m.group(1) + crs_type + m.group(2), content)

    # A bare relative output name has no dirname; makedirs('') raises
    # WinError 3 (audit 2026-08-07).
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8', newline='') as f:
        f.write(content)
    return output_path
