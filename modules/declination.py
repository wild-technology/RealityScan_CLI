"""Magnetic declination for a dive, and whether it should be applied at all.

Owner directive 2026-09-06: "Mag declination should be estimated from the UTM
Zone if available."

Two things had to be settled before that could be implemented, and both change
the answer:

1. **A UTM zone cannot give a usable declination.** A zone is a 6-degree
   longitude band with NO latitude information, and declination varies with
   both. What the pipeline actually holds at the moment of need is much
   better: the per-image ``LAT``/``LONG`` it just computed, and a parsed UTC
   timestamp per nav row. So the estimate keys off the MEDIAN accepted
   position and the MEDIAN timestamp, not off the zone.

2. **Most of this project's nav must NOT be corrected.** ROVDataConcat's
   ``*_final_datatable.csv`` carries ``kalman_yaw_deg``, a Kalman-filtered
   heading whose source is an Octans fibre-optic gyrocompass. A gyrocompass
   finds TRUE north directly - it has no magnetic sensor - so that heading is
   already true and adding a declination injects the full declination as
   error. HANDOFF.md: "no declination is applied anywhere, kalman_yaw_deg
   comes from an Octans gyrocompass, so it is TRUE north and decl = 0 is
   correct - the repo's HEADING_MAG name is a misnomer." On NA165/H2060 the
   WMM value is +12.19 deg against a 15 deg declared yaw accuracy, so getting
   this backwards would spend 81% of the orientation budget on a systematic
   offset.

Hence: ESTIMATE ALWAYS, APPLY ONLY WHEN THE SOURCE IS MAGNETIC. The computed
value is recorded either way so a solve can be reproduced and audited.

The model is the WMM via ``pygeomag`` - pure Python, coefficients bundled, no
network. Epoch selection is mandatory rather than cosmetic: each WMM release is
valid for five years and ``pygeomag`` raises outright outside that window, so a
2024 dive must be evaluated against WMM_2020 even though WMM_2025 is the
library default.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
import re

logger = logging.getLogger(__name__)

# WMM coefficient files bundled with pygeomag, and the window each covers.
# WMMHR_* are excluded deliberately: pygeomag 1.1.0 raises IndexError on them
# (measured 2026-09-06), so a "high resolution" choice is a broken run.
_EPOCHS: tuple[tuple[float, float, str], ...] = (
    (2010.0, 2015.0, 'wmm/WMM_2010.COF'),
    (2015.0, 2020.0, 'wmm/WMM_2015v2.COF'),
    (2020.0, 2025.0, 'wmm/WMM_2020.COF'),
    (2025.0, 2030.0, 'wmm/WMM_2025.COF'),
)

# Column names that identify a gyrocompass-derived (already TRUE) heading.
# kalman_yaw_deg is ROVDataConcat's filtered Octans heading; the octans token
# covers the raw per-sensor table.
_TRUE_HEADING_COLUMNS = ('kalman_yaw_deg',)
_TRUE_HEADING_FILE_TOKENS = ('octans', 'gyro')


class DeclinationUnavailable(Exception):
    """No field model, or no epoch covering the requested date."""


def decimal_year(when: _dt.datetime) -> float:
    """Fractional year, the form WMM evaluation takes."""
    start = _dt.datetime(when.year, 1, 1)
    end = _dt.datetime(when.year + 1, 1, 1)
    return when.year + (when - start).total_seconds() / (end - start).total_seconds()


def coefficient_file_for(year: float) -> str:
    """The bundled WMM file whose 5-year window contains ``year``."""
    for lo, hi, path in _EPOCHS:
        if lo <= year < hi:
            return path
    raise DeclinationUnavailable(
        f'No bundled WMM epoch covers {year:.3f} (available: '
        + ', '.join(f'{lo:.0f}-{hi:.0f}' for lo, hi, _ in _EPOCHS) + ')')


def wmm_declination(lat: float, lon: float, when: _dt.datetime,
                    alt_km: float = 0.0) -> float:
    """Magnetic declination in degrees, EAST POSITIVE.

    Raises DeclinationUnavailable when pygeomag is absent or no epoch covers
    the date - never returns a silent 0.0, because 0.0 is a legitimate value
    and must not double as "could not compute".
    """
    try:
        from pygeomag import GeoMag
    except ImportError as exc:                                   # noqa: BLE001
        raise DeclinationUnavailable(
            'pygeomag is not installed - cannot estimate declination. '
            'pip install pygeomag (pure Python, coefficients bundled, works '
            'offline).') from exc

    year = decimal_year(when)
    coefficients = coefficient_file_for(year)
    try:
        result = GeoMag(coefficients_file=coefficients).calculate(
            glat=float(lat), glon=float(lon), alt=float(alt_km), time=year)
    except Exception as exc:                                     # noqa: BLE001
        raise DeclinationUnavailable(
            f'WMM evaluation failed for lat={lat} lon={lon} at {year:.3f} '
            f'using {coefficients}: {type(exc).__name__}: {exc}') from exc
    return float(result.d)


def heading_reference(nav_path: str | None = None,
                      columns: object = None) -> str:
    """``'true'``, ``'magnetic'`` or ``'unknown'`` for a nav source.

    Detection is by COLUMN NAME first (the reliable signal - ROVDataConcat's
    kalman_yaw_deg is Octans-derived) and by filename token second. Anything
    unrecognised is 'unknown', which callers must treat as "do not silently
    correct", because a wrong correction is indistinguishable from good data
    downstream.
    """
    names = []
    if columns is not None:
        try:
            names = [str(c).strip().lower() for c in columns]
        except TypeError:
            names = []
    for wanted in _TRUE_HEADING_COLUMNS:
        if wanted in names:
            return 'true'
    if nav_path:
        stem = os.path.basename(str(nav_path)).lower()
        if any(tok in stem for tok in _TRUE_HEADING_FILE_TOKENS):
            return 'true'
        if re.search(r'(^|[_\-])mag(netic)?([_\-.]|$)', stem):
            return 'magnetic'
    return 'unknown'


def resolve(lat: float | None, lon: float | None,
            when: _dt.datetime | None,
            nav_path: str | None = None,
            columns: object = None,
            operator_value: float | None = None,
            logger_=None) -> dict:
    """Decide the declination this run will APPLY, and record the estimate.

    Returns a dict recorded verbatim with the run:
        applied_deg   - what the yaw computation will actually add
        estimated_deg - the WMM value at the dive's own position/date, or None
        reference     - 'true' | 'magnetic' | 'unknown'
        source        - 'operator' | 'wmm' | 'gyrocompass-true' | 'unavailable'
        reason        - one human-readable sentence

    An EXPLICIT operator value always wins: this is an estimator, not an
    override. It is still reported alongside the estimate so a disagreement is
    visible rather than buried.
    """
    log = logger_ or logger
    reference = heading_reference(nav_path, columns)

    estimated = None
    estimate_error = None
    if lat is not None and lon is not None and when is not None:
        try:
            estimated = wmm_declination(lat, lon, when)
        except DeclinationUnavailable as exc:
            estimate_error = str(exc)
            log.warning('Declination estimate unavailable: %s', exc)
    else:
        estimate_error = ('no position/date available at the point of '
                          'estimation')

    if operator_value is not None:
        out = {'applied_deg': float(operator_value), 'estimated_deg': estimated,
               'reference': reference, 'source': 'operator',
               'reason': 'operator supplied --g_declination explicitly'}
        if estimated is not None and abs(estimated - float(operator_value)) > 1.0:
            log.warning(
                'Operator declination %.3f deg differs from the WMM estimate '
                '%.3f deg at this site/date. Using the operator value.',
                float(operator_value), estimated)
        return out

    if reference == 'true':
        # The decisive branch. The heading is already true north, so the
        # correct correction is exactly zero - and it is zero BECAUSE the
        # source was identified, not because nothing was computed.
        log.info(
            'Heading reference: TRUE (gyrocompass-derived, %s). Declination '
            'APPLIED = 0.0 deg. WMM at this site/date would be %s - NOT '
            'applied; adding it would inject that much pure error into every '
            'yaw prior.', nav_path or 'by column name',
            'unavailable' if estimated is None else f'{estimated:+.3f} deg')
        return {'applied_deg': 0.0, 'estimated_deg': estimated,
                'reference': 'true', 'source': 'gyrocompass-true',
                'reason': 'nav heading is gyrocompass TRUE north; no '
                          'declination correction is applicable'}

    if reference == 'magnetic' and estimated is not None:
        log.info('Heading reference: MAGNETIC. Applying WMM declination '
                 '%+.3f deg (east positive).', estimated)
        return {'applied_deg': estimated, 'estimated_deg': estimated,
                'reference': 'magnetic', 'source': 'wmm',
                'reason': 'nav heading is magnetic; corrected to true north '
                          'with the WMM value for this position and date'}

    # Unknown reference, or magnetic with no model available. Do not guess.
    log.warning(
        'Heading reference could NOT be established for %s (columns did not '
        'name a known true-heading source, filename gave no hint). Declination '
        'APPLIED = 0.0 deg. WMM estimate: %s. If this nav is magnetic, pass '
        '--g_declination explicitly - an unapplied correction is visible in '
        'the residuals, a wrongly applied one is not.',
        nav_path or 'the nav source',
        'unavailable' if estimated is None else f'{estimated:+.3f} deg')
    return {'applied_deg': 0.0, 'estimated_deg': estimated,
            'reference': reference,
            'source': 'unavailable' if estimated is None else 'wmm',
            'reason': estimate_error or ('heading reference unknown; no '
                                         'correction applied')}
