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


def find_flight_log(*directories: str | None) -> str | None:
    """Return the first flight log found across the candidate directories.

    All directories are searched for current-format ``flight_log*_UTM.txt``
    logs before any is searched for a legacy ``flight_log.txt``, so a
    georeferenced log always wins over a stale legacy one. Multiple UTM
    logs in one directory resolve to the lexicographically first for
    determinism. Returns ``None`` when nothing matches.
    """
    valid = [d for d in directories if d and os.path.isdir(d)]

    for directory in valid:
        matches = sorted(glob.glob(os.path.join(directory, 'flight_log*_UTM.txt')))
        if matches:
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


def epsg_for_utm_zone(zone: int, band: str) -> int:
    """EPSG code for a WGS84 UTM zone: 326xx north, 327xx south."""
    return (32700 if band.upper() in _SOUTH_BANDS else 32600) + zone


def write_flight_log_params(template_path: str, output_path: str,
                            zone: int, band: str) -> str:
    """Copy the FlightLogParams template with its coordinate system
    rewritten for the given UTM zone. Returns output_path.

    RealityScan mis-imports every trajectory silently when the params XML
    declares the wrong zone (HANDOFF.md: NA173 logs were zone 57S while
    the template still said 4N), so the zone must always come from the
    flight log itself, never from a hand-edited template.
    """
    epsg = epsg_for_utm_zone(zone, band)
    south = ' +south' if band.upper() in _SOUTH_BANDS else ''
    hemisphere = 'S' if south else 'N'
    proj = f'+proj=utm +zone={zone}{south} +datum=WGS84 +units=m +no_defs'
    crs_type = f'epsg:{epsg} - WGS 84 / UTM zone {zone}{hemisphere}'

    with open(template_path, encoding='utf-8') as f:
        content = f.read()
    content = re.sub(
        r'(<entry key="CoordinateSystemFlightLog" value=")[^"]*("/>)',
        lambda m: m.group(1) + proj + m.group(2), content)
    content = re.sub(
        r'(<entry key="CoordinateSystemFlightLogType" value=")[^"]*("/>)',
        lambda m: m.group(1) + crs_type + m.group(2), content)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8', newline='') as f:
        f.write(content)
    return output_path
