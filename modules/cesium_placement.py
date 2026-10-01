#!/usr/bin/env python3
"""Place a RealityScan mesh export on the WGS84 globe for Cesium ion.

Cesium ion renders every height as metres above the WGS84 ELLIPSOID
(CesiumJS ``Cartographic.height`` is defined that way). This pipeline's
vertical is nothing of the kind: ``geoall.py`` writes ``-abs(kalman_depth)``
into the flight log's ``Alt`` column, so the Z that reaches an exported model
is depth below the instantaneous SEA SURFACE - an orthometric height, referred
to the geoid. Handing that number to ion unchanged sinks or floats the whole
asset by the local geoid undulation N: +4.5 m at Papahanaumokuakea, +15.9 m at
Oahu, -27.1 m in the Gulf of Mexico, **+70.4 m in the Solomon Sea** - the very
UTM zone the shared ``FlightLogParams.xml`` template carries. The conversion
is ``h = H + N`` with ``H = -depth``.

Three further traps, each found the expensive way and each guarded here:

1. **PROJ applies a SILENT ZERO correction when the geoid grid is missing.**
   ``Transformer.from_crs('EPSG:9518', 'EPSG:4979')`` succeeds offline and
   returns Z unchanged, having quietly selected a "ballpark vertical
   transformation, without ellipsoid height to vertical height correction".
   No exception, no warning - a textbook silent success. Every transformer
   built here passes ``allow_ballpark=False``, which raises instead.

2. **Exported vertices are not necessarily in the global CRS.** The NA168
   H2080 OBJ sits in a scrambled local frame ~350 km from the site; its
   ``.rsInfo`` sidecar carries the ``transformToModel`` matrix that puts it
   back. The 16 stored numbers do not have one obvious reading, so this module
   does not guess: it applies every candidate interpretation and accepts only
   the one whose output lands inside the declared CRS's area of use (and
   inside the nav envelope, when a flight log is supplied). Zero or more than
   one survivor is an error, never a default.

3. **A projected grid is not East-North-Up.** Grid north is turned from true
   north by the meridian convergence and a grid metre is not a true metre:
   at NA165/H2060, 210 km from the central meridian of UTM zone 2S, by
   -0.4797 deg and 1.000149 (1.000251 with the mesh 650 m below the
   ellipsoid). Subtracting the anchor from eastings and northings and
   calling the result East / North - what this module did until 2026-10-01,
   BUGS.md B28 - turns every projected upload about its anchor by the
   convergence. A projected export is now taken to the SAME true local frame
   the geocentric one gets: grid -> geodetic -> ECEF -> ENU at the anchor,
   its ``vn`` normals turned with it.

Cesium ion wants photogrammetry uploaded in LOCAL coordinates centred on the
origin, with placement supplied as ``options.position = [lon, lat, height]``
(documented verbatim: "The origin of the tileset in [longitude, latitude,
height] format in EPSG:4326 coordinates and height in meters"). So the output
of this module is a local East-North-Up mesh plus that anchor - which also
disposes of the precision problem, since raw UTM eastings carry ~350 000 m of
magnitude that an ASCII OBJ spends its significant digits on.

Nothing here talks to the network except the geoid grid fetch, and nothing
here talks to RealityScan. See ``publish_cesium.py`` for the upload driver.
"""
from __future__ import annotations

import itertools
import logging
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# EPSG:9518 = WGS 84 + EGM2008 height. PROJ resolves it identically to the
# compound 'EPSG:4326+3855'. EGM2008 (grid us_nga_egm08_25.tif, ~80 MB from
# cdn.proj.org) is the only 2.5-arc-minute geoid PROJ can actually fetch;
# EPSG:5714 (MSL height) needs an NGA grid that is not redistributable, and
# EPSG:5715 (MSL depth) has no transformation to an ellipsoidal CRS at all.
GEOID_CRS = {'EGM2008': 'EPSG:9518', 'EGM96': 'EPSG:9707'}
WGS84_3D = 'EPSG:4979'
WGS84_2D = 'EPSG:4326'

# A UTM easting is always 100 km..900 km and a northing 0..10 000 km. Used
# only as a cheap pre-filter; the authoritative test is the CRS area of use.
_PROJECTED_SANITY = {'east': (-1.0e7, 1.0e7), 'north': (-1.0e7, 2.0e7)}


class PlacementError(RuntimeError):
    """Raised when placement cannot be established with evidence."""


@dataclass(frozen=True)
class RSInfo:
    """The ``<Model>`` half of a ``<model>.<ext>.rsInfo`` export sidecar."""

    path: Path
    crs_proj: str | None
    crs_name: str | None
    crs_wkt: str | None
    export_cs_type: str | None
    transform: tuple[float, ...] | None

    @property
    def epsg(self) -> str | None:
        """``'EPSG:32653'`` parsed from ``globalCoordinateSystemName``."""
        if not self.crs_name:
            return None
        match = re.search(r'epsg:(\d+)', self.crs_name, re.IGNORECASE)
        return f'EPSG:{match.group(1)}' if match else None

    @property
    def crs(self) -> str:
        """The best CRS string available, preferring an EPSG code.

        WKT is the last resort: it round-trips through pyproj but is far
        harder to eyeball in a log than ``EPSG:32653``.
        """
        for candidate in (self.epsg, self.crs_proj, self.crs_wkt):
            if candidate:
                return candidate
        raise PlacementError(
            f'{self.path} declares no coordinate system: the export was not '
            'georeferenced, so there is nothing to place it by. Re-export '
            'with a georeferenced model-export preset '
            '(MvsExportIsGeoreferenced=0x1).')

    @property
    def is_geocentric(self) -> bool:
        """True when the exported VERTICES are ECEF, not the declared CRS.

        ``exportCoordinateSystemType="3"`` is RealityScan's geocentric
        mesh export. ``globalCoordinateSystemName`` still names the
        PROJECT's projected CRS, so reading the vertices as easting /
        northing / height puts the asset on the far side of the planet:
        measured 2026-09-23 on NA168/H2077, whose ECEF vertices read as
        UTM 53N anchored the asset at lon 87.12 lat 30.98 +832 km - over
        Tibet, in low orbit - when the dive is at 132.8E 7.5N.

        Keying on the type rather than the declared CRS also makes a
        WRONG label harmless, which matters because they occur: NA165's
        H2063 shipped c00 labelled epsg:32653, a 53N zone left over from
        the previous campaign, while c22 of the same dive declared
        epsg:32702. Both were ECEF; reading the type places both.

        Surveyed across NA168/H2077 and NA165/H2063 (2026-09-23): every
        type-3 sidecar sits beside ECEF vertices, and the PLY dense
        exports carry type 0.
        """
        return str(self.export_cs_type).strip() == '3'

    @property
    def vertex_crs(self) -> str:
        """The CRS the vertices are ACTUALLY in - EPSG:4978 for a
        geocentric export, otherwise the declared CRS."""
        return 'EPSG:4978' if self.is_geocentric else self.crs


@dataclass(frozen=True)
class Interpretation:
    """One candidate reading of the 16 ``transformToModel`` numbers."""

    layout: str   # 'row-major' | 'col-major'
    mode: str     # 'Mv' (column-vector) | 'vM' (row-vector)
    perm: tuple[int, int, int]

    def __str__(self) -> str:
        return f'{self.layout}/{self.mode}/perm{self.perm}'


# --------------------------------------------------------------------------
# .rsInfo sidecar
# --------------------------------------------------------------------------

def find_rsinfo(model_path: Path) -> Path | None:
    """``<model>.<ext>.rsInfo`` beside a model, or the legacy ``.rcInfo``.

    RealityScan 2.2 writes ``.rsInfo``; projects carried over from
    RealityCapture still hold ``.rcInfo``. Both spellings appear on disk with
    inconsistent case, so match case-insensitively.
    """
    for suffix in ('.rsInfo', '.rcInfo'):
        for candidate in (model_path.parent).glob('*'):
            if (candidate.name.lower() == (model_path.name + suffix).lower()
                    and candidate.is_file()):
                return candidate
    return None


def parse_rsinfo(path: Path) -> RSInfo:
    """Parse the ``<Model>`` tag of an export sidecar.

    The file is a sequence of sibling top-level tags (``<Model>``,
    ``<ModelExport>``, ``<CalibrationExportSettings>``) with no single root,
    so it is not well-formed XML on its own - wrap it before parsing.
    """
    raw = path.read_text(encoding='utf-8-sig', errors='replace')
    try:
        root = ET.fromstring(f'<rsInfo>{raw}</rsInfo>')
    except ET.ParseError as exc:
        raise PlacementError(f'{path} is not parseable as XML: {exc}') from exc

    model = root.find('Model')
    if model is None:
        raise PlacementError(
            f'{path} has no <Model> tag, so it records no coordinate system. '
            'A sidecar without one cannot place the mesh.')

    wkt_el = model.find('globalCoordinateSystemWkt')
    transform = None
    # RealityScan writes the matrix either as a child element or as an
    # attribute - the OBJ sidecar uses the element, the LAS one the attribute.
    raw_matrix = model.attrib.get('transformToModel')
    matrix_el = model.find('transformToModel')
    if matrix_el is not None and matrix_el.text:
        raw_matrix = matrix_el.text
    if raw_matrix:
        values = raw_matrix.split()
        if len(values) != 16:
            raise PlacementError(
                f'{path}: transformToModel has {len(values)} values, expected '
                '16 (a 4x4 matrix). Refusing to guess at a malformed matrix.')
        try:
            transform = tuple(float(v) for v in values)
        except ValueError as exc:
            raise PlacementError(
                f'{path}: transformToModel is not all numeric: {exc}') from exc

    return RSInfo(
        path=path,
        crs_proj=model.attrib.get('globalCoordinateSystem'),
        crs_name=model.attrib.get('globalCoordinateSystemName'),
        crs_wkt=(wkt_el.text.strip() if wkt_el is not None and wkt_el.text
                 else None),
        export_cs_type=model.attrib.get('exportCoordinateSystemType'),
        transform=transform,
    )


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------

def read_obj_vertices(obj_path: Path):
    """The ``v`` lines of an OBJ as an (N, 3) float64 array.

    Streamed rather than slurped: a textured deliverable OBJ runs to hundreds
    of MB and this is called on every part.
    """
    import numpy as np

    coords: list[float] = []
    count = 0
    with obj_path.open('r', encoding='utf-8', errors='replace') as handle:
        for line in handle:
            if line.startswith('v '):
                parts = line.split()
                if len(parts) < 4:
                    raise PlacementError(
                        f'{obj_path}: malformed vertex line {line!r}')
                coords.extend((float(parts[1]), float(parts[2]),
                               float(parts[3])))
                count += 1
    if not count:
        raise PlacementError(f'{obj_path} contains no vertices')
    return np.asarray(coords, dtype='float64').reshape(count, 3)


def _candidates() -> list[Interpretation]:
    return [Interpretation(layout, mode, perm)
            for layout in ('row-major', 'col-major')
            for mode in ('Mv', 'vM')
            for perm in itertools.permutations(range(3))]


def _linear_part(transform: tuple[float, ...], interp: Interpretation):
    """The composed 3x3 that a reading applies to a vector."""
    import numpy as np

    matrix = np.asarray(transform, dtype='float64').reshape(4, 4)
    if interp.layout == 'col-major':
        matrix = matrix.T
    if interp.mode == 'vM':
        matrix = matrix.T
    return matrix[:3, :3][list(interp.perm), :]


def preserves_orientation(transform: tuple[float, ...],
                          interp: Interpretation) -> bool:
    """True when a reading is a proper (non-mirroring) transform.

    This is what separates the two readings that the CRS area of use cannot
    tell apart. On NA168 H2080 both ``perm(1,2,0)`` and ``perm(2,1,0)`` put
    every vertex inside UTM zone 53N - the site's easting (~348 355) and
    northing (~396 320) are each plausible as the other - but ``perm(2,1,0)``
    swaps East and North, and a single axis swap is a REFLECTION with
    determinant -1. A reflected mesh is mirror-imaged, which no coordinate
    transform between two right-handed frames can produce, so the negative
    determinant rules it out on geometry rather than on plausibility.
    """
    import numpy as np

    determinant = float(np.linalg.det(_linear_part(transform, interp)))
    return determinant > 0.0


def apply_interpretation(vertices, transform: tuple[float, ...],
                         interp: Interpretation):
    """Map model-frame vertices to the global CRS under one reading."""
    import numpy as np

    matrix = np.asarray(transform, dtype='float64').reshape(4, 4)
    if interp.layout == 'col-major':
        matrix = matrix.T
    if interp.mode == 'vM':
        matrix = matrix.T
    homogeneous = np.c_[vertices, np.ones(len(vertices))]
    out = (homogeneous @ matrix.T)[:, :3]
    return out[:, list(interp.perm)]


def _crs_bounds(crs: str) -> tuple[float, float, float, float] | None:
    """(west, south, east, north) area of use in degrees, or None."""
    from pyproj import CRS

    area = CRS.from_user_input(crs).area_of_use
    if area is None:
        return None
    return (area.west, area.south, area.east, area.north)


def _fraction_inside(points_en, crs: str,
                     bounds: tuple[float, float, float, float]) -> float:
    """Fraction of (easting, northing) rows landing inside the CRS's own
    area of use, after conversion to lon/lat."""
    import numpy as np
    from pyproj import Transformer

    east, north = points_en[:, 0], points_en[:, 1]
    lo, hi = _PROJECTED_SANITY['east']
    finite = np.isfinite(east) & np.isfinite(north)
    if not finite.any():
        return 0.0
    plausible = finite & (east > lo) & (east < hi)
    if not plausible.any():
        return 0.0

    to_geo = Transformer.from_crs(crs, WGS84_2D, always_xy=True)
    lon, lat = to_geo.transform(east[plausible], north[plausible])
    west, south, e_bound, north_bound = bounds
    ok = (np.isfinite(lon) & np.isfinite(lat)
          & (lon >= west) & (lon <= e_bound)
          & (lat >= south) & (lat <= north_bound))
    # Rows filtered out earlier count as misses, so a partially-valid
    # interpretation cannot beat a wholly-valid one.
    return float(ok.sum()) / float(len(points_en))


def resolve_to_global(vertices, info: RSInfo,
                      nav_envelope: dict | None = None,
                      sample: int = 20000):
    """Model-frame vertices -> global CRS, with the reading it took.

    Every candidate reading of ``transformToModel`` is applied and scored by
    the fraction of vertices landing inside the declared CRS's area of use
    (and inside ``nav_envelope``, when given). Exactly one candidate must
    qualify; zero or several is a hard error, because a wrong reading here
    silently relocates the asset by hundreds of kilometres.

    ``nav_envelope`` is ``{'east': (lo, hi), 'north': (lo, hi),
    'alt': (lo, hi)}`` - typically the min/max of a dive's flight log.
    """
    import numpy as np

    crs = info.vertex_crs
    if info.transform is None:
        logger.info('%s carries no transformToModel; treating the mesh as '
                    'already in %s', info.path.name, crs)
        return vertices, None

    identity = np.eye(4).reshape(-1)
    if np.allclose(np.asarray(info.transform), identity, atol=1e-12):
        logger.info('%s carries an identity transformToModel; the mesh is '
                    'already in %s', info.path.name, crs)
        return vertices, None

    bounds = _crs_bounds(crs)
    if bounds is None:
        raise PlacementError(
            f'{crs} declares no area of use, so a candidate transform cannot '
            'be validated against it. Supply a flight log to validate '
            'against the nav envelope instead.')

    # Score on a sample: the winner separates from the losers by ~0.67, so a
    # few thousand vertices decide it, and a 20 M-vertex mesh stays cheap.
    step = max(1, len(vertices) // sample)
    probe = vertices[::step]

    scored: list[tuple[float, Interpretation]] = []
    for interp in _candidates():
        if not preserves_orientation(info.transform, interp):
            continue
        transformed = apply_interpretation(probe, info.transform, interp)
        score = _fraction_inside(transformed, crs, bounds)
        if nav_envelope and score > 0.0:
            score = min(score, _nav_score(transformed, nav_envelope))
        scored.append((score, interp))

    if not scored:
        raise PlacementError(
            f'every reading of transformToModel in {info.path.name} mirrors '
            'the geometry (negative determinant). The matrix is not a valid '
            'rigid transform between right-handed frames.')

    scored.sort(key=lambda item: -item[0])
    winners = [interp for score, interp in scored if score >= 0.999]
    best_score, best = scored[0]

    if not winners:
        raise PlacementError(
            f'no reading of transformToModel in {info.path.name} puts the '
            f'mesh inside the area of use of {crs} '
            f'(best was {best} at {best_score:.4f}). The sidecar CRS and the '
            'geometry disagree; placing this mesh would be a guess.')
    if len(winners) > 1:
        distinct = {
            tuple(np.round(
                apply_interpretation(probe[:1], info.transform, w)[0], 6))
            for w in winners}
        if len(distinct) > 1:
            raise PlacementError(
                f'{len(winners)} readings of transformToModel in '
                f'{info.path.name} are all valid for {crs} and disagree about '
                f'where the mesh goes ({sorted(map(str, winners))}). '
                'Refusing to pick one.')
        logger.debug('%d equivalent readings agreed; using %s',
                     len(winners), winners[0])

    chosen = winners[0]
    logger.info('transformToModel read as %s (%.4f of vertices inside %s)',
                chosen, best_score, crs)
    return apply_interpretation(vertices, info.transform, chosen), chosen


def _nav_score(points, envelope: dict) -> float:
    """Fraction of rows inside a nav (flight-log) envelope."""
    import numpy as np

    total = 0.0
    for index, key in enumerate(('east', 'north', 'alt')):
        if key not in envelope:
            continue
        low, high = envelope[key]
        column = points[:, index]
        total += float(((column >= low) & (column <= high)).mean())
    keys = sum(1 for key in ('east', 'north', 'alt') if key in envelope)
    return total / keys if keys else 1.0


# --------------------------------------------------------------------------
# Vertical datum
# --------------------------------------------------------------------------

def geoid_separation(lon: float, lat: float,
                     model: str = 'EGM2008') -> float:
    """Geoid undulation N in metres at a point: ``h = H + N``.

    Built with ``allow_ballpark=False`` so that a missing grid RAISES rather
    than silently returning a zero correction. PROJ only ships usable
    transformations for EGM96 and EGM2008; the grid is fetched from
    cdn.proj.org on first use, so enable PROJ network access (see
    :func:`enable_geoid_network`) or install the grid locally.
    """
    from pyproj import Transformer
    from pyproj.exceptions import ProjError

    if model not in GEOID_CRS:
        raise PlacementError(
            f'unknown geoid model {model!r}; choose one of '
            f'{sorted(GEOID_CRS)}')
    try:
        transformer = Transformer.from_crs(
            GEOID_CRS[model], WGS84_3D, always_xy=True, allow_ballpark=False)
    except ProjError as exc:
        raise PlacementError(
            f'no {model} geoid transformation is available: {exc}. PROJ needs '
            f'the geoid grid (EGM2008 -> us_nga_egm08_25.tif, ~80 MB from '
            'cdn.proj.org). Enable network access with PROJ_NETWORK=ON, or '
            'install the grid with "projsync --file us_nga_egm08_25.tif". '
            'Refusing to continue: without the grid PROJ silently applies a '
            'ZERO correction and the asset would be placed off by the local '
            'undulation (up to ~70 m in the Solomon Sea).') from exc

    separation = transformer.transform(lon, lat, 0.0)[2]
    if separation is None or separation != separation:  # NaN guard
        raise PlacementError(
            f'{model} geoid separation came back undefined at '
            f'lon={lon}, lat={lat}')
    return float(separation)


def enable_geoid_network() -> None:
    """Let PROJ fetch geoid grids from cdn.proj.org.

    Off by default in pyproj, and its absence is exactly what turns the
    vertical correction into a silent no-op.
    """
    import pyproj.network

    pyproj.network.set_network_enabled(True)


def msl_to_ellipsoidal(depth_msl: float, lon: float, lat: float,
                       model: str = 'EGM2008') -> tuple[float, float]:
    """(ellipsoidal height, N) for a sea-surface-referenced height.

    ``depth_msl`` is the pipeline's own convention: negative metres DOWN from
    the sea surface, exactly as ``geoall.py`` writes ``ALTITUDE_EST``.
    """
    separation = geoid_separation(lon, lat, model)
    return depth_msl + separation, separation


# --------------------------------------------------------------------------
# Local ENU frame
# --------------------------------------------------------------------------

#: Vertices handed to PROJ per call on the projected route. It bounds the
#: temporaries (a handful of float64 columns of this length) whatever the
#: mesh size, so a 24-million-vertex component costs its input and output
#: arrays and nothing else that grows with it.
ENU_CHUNK = 1 << 20


def check_projected_crs(crs: str) -> str:
    """The name of a CRS a non-geocentric export can be localised from -
    or a refusal that says what the CRS itself declares.

    Supported: ONE projected CRS whose first axis is its easting and second
    its northing, both in metres (and a third, if it has one, up in metres).
    That is every UTM zone in either hemisphere, and equally a transverse
    Mercator on its own meridian or a polar stereographic grid; the
    projection itself is PROJ's business, exactly, whatever it is.

    Refused, because the columns of the OBJ could only be guessed at:

    - a geographic CRS (X / Y in degrees) or a geocentric one on an export
      that is not type 3;
    - a compound CRS - it names a vertical datum, and this module derives
      the vertical itself (Z is -depth below the sea surface, + N);
    - axes that are not easting-then-northing (a northing-first national
      grid, a westing / southing one). This module reads an OBJ's first
      column as the easting. Every RealityScan export seen so far is in a
      CRS that says the same; none exists in a CRS that says otherwise to
      check the column order against;
    - a unit that is not the metre. PROJ would convert the eastings and
      northings, but nothing in the sidecar says what unit Z is in.

    Axis order and unit are READ from the CRS, never assumed.
    """
    from pyproj import CRS
    from pyproj.exceptions import CRSError

    try:
        parsed = CRS.from_user_input(crs)
    except CRSError as exc:
        raise PlacementError(
            f'the export CRS {crs!r} cannot be read by PROJ: {exc}') from exc
    label = f'{crs} ({parsed.name})' if parsed.name not in crs else crs

    if parsed.is_compound:
        raise PlacementError(
            f'{label} is a compound CRS: it names a vertical datum of its '
            'own. This module derives the vertical itself (Z is read as '
            '-depth below the sea surface and the geoid undulation is added '
            'to the anchor) and has never been checked against a compound '
            'export. Refusing rather than ignoring what the CRS declares; '
            're-export in the projected CRS alone.')
    if parsed.is_geographic:
        raise PlacementError(
            f'{label} is a geographic CRS, so the vertices would be degrees '
            'of longitude and latitude. No RealityScan export seen so far is '
            'in one and the order of its two columns cannot be checked. '
            'Re-export in a projected CRS in metres, or as a geocentric '
            'model (exportCoordinateSystemType 3).')
    if parsed.is_geocentric:
        raise PlacementError(
            f'{label} is a geocentric CRS but the export is not marked '
            'geocentric (exportCoordinateSystemType is not 3). The sidecar '
            'contradicts itself; refusing to choose a reading.')
    if not parsed.is_projected:
        raise PlacementError(
            f'{label} is a {parsed.type_name}, not a projected CRS; there is '
            'no easting / northing to place the mesh by.')

    axes = parsed.axis_info
    described = ', '.join(
        f'{axis.name} [{axis.direction}, {axis.unit_name}]' for axis in axes)
    if len(axes) < 2:
        raise PlacementError(
            f'{label} declares {len(axes)} axis(es) ({described}); an '
            'easting and a northing are needed.')
    first, second = axes[0], axes[1]
    east_north = (first.direction, second.direction) == ('east', 'north')
    # A polar grid's axes both run along meridians ("north" or "south"), so
    # there the names decide.
    named = ((first.name or '').strip().lower(),
             (second.name or '').strip().lower()) == ('easting', 'northing')
    polar = first.direction == second.direction and first.direction in (
        'north', 'south')
    if not (east_north or (named and polar)):
        raise PlacementError(
            f'{label} lists its axes as {described}. This module reads an '
            'OBJ\'s first column as the easting and its second as the '
            'northing, and has no RealityScan export in a CRS with another '
            'axis order to check the columns against. Refusing rather than '
            'guessing which column is which.')
    for axis in axes[:2]:
        if abs(axis.unit_conversion_factor - 1.0) > 1e-12:
            raise PlacementError(
                f'{label} is in {axis.unit_name} ({described}), not metres. '
                'PROJ could convert the eastings and northings, but the '
                'sidecar does not say what unit Z is in and the depth -> '
                'height arithmetic here assumes metres. Re-export in a '
                'metric CRS.')
    if len(axes) > 2 and (axes[2].direction != 'up' or abs(
            axes[2].unit_conversion_factor - 1.0) > 1e-12):
        raise PlacementError(
            f'{label} has a third axis that is not a height in metres '
            f'({described}). Z is read here as metres UP (-depth).')
    return parsed.name


@dataclass(frozen=True)
class ProjectedFrame:
    """The true East-North-Up frame at a projected export's anchor."""

    crs: str
    anchor: tuple[float, float, float]        # E, N, Z in the CRS
    lon: float
    lat: float
    anchor_ecef: tuple[float, float, float]
    # Grid axes -> ENU at the anchor: a proper rotation (about Up, for a
    # conformal grid). What the ``vn`` normals are turned by.
    rotation: tuple[tuple[float, float, float], ...]
    # Azimuth of grid north, clockwise from true north - PROJ's meridian
    # convergence, same sign.
    convergence_deg: float
    # Grid metres per true horizontal metre at the anchor: the projection's
    # scale factor k, divided by (1 + h / R) for a mesh h above the
    # ellipsoid (a mesh at depth is smaller on the ground than on the grid).
    grid_per_true_metre: float


def _projected_transformers(crs: str):
    """(grid -> lon / lat, lon / lat / h -> ECEF) for a projected CRS.

    The first is built exactly as the anchor's own lon / lat is, so the
    local frame is centred on the plan position by construction.
    """
    from pyproj import Transformer

    return (Transformer.from_crs(crs, WGS84_2D, always_xy=True),
            Transformer.from_crs(WGS84_3D, 'EPSG:4978', always_xy=True))


def _projected_block_to_enu(block, transformers, anchor_ecef, lon: float,
                            lat: float):
    """One block of (E, N, Z) rows -> local ENU, by the reference route:
    grid -> geodetic by PROJ, Z as the height, geodetic -> ECEF, and then
    the geocentric route's own ECEF -> ENU."""
    import numpy as np

    # PROJ's point shortcut takes a ONE-element array through float(),
    # which NumPy is retiring (a DeprecationWarning since 1.25). A lone
    # vertex is sent twice instead, so every block goes the array way.
    rows = len(block)
    if rows == 1:
        block = np.vstack((block, block))
    to_geo, to_ecef = transformers
    lons, lats = to_geo.transform(block[:, 0], block[:, 1])
    x, y, z = to_ecef.transform(lons, lats, block[:, 2])
    return to_local_enu_from_ecef(np.column_stack((x, y, z)), anchor_ecef,
                                  lon, lat)[0][:rows]


def projected_frame(crs: str, anchor) -> ProjectedFrame:
    """The local frame a projected export is taken to, and how far the grid
    is from it at the anchor.

    ``anchor`` is (E, N, Z) in ``crs``. Its Z goes into the ELLIPSOIDAL
    slot unchanged, as RealityScan puts the flight log's -depth into an
    ECEF export, so the mesh is the same with and without the geoid; N is
    added to the height ion is given and to nothing else.

    The rotation is MEASURED, not looked up: the reference route is
    differenced one metre each way along every grid axis and the turn is
    the rotation nearest that Jacobian (its polar factor). It therefore
    describes what the vertices actually undergo, for any projection.
    """
    import numpy as np

    east, north, height = (float(v) for v in anchor)
    transformers = _projected_transformers(crs)
    lon, lat = transformers[0].transform(east, north)
    if not (np.isfinite(lon) and np.isfinite(lat)):
        raise PlacementError(
            f'anchor easting/northing {(east, north)} does not convert to '
            f'lon/lat under {crs}')
    anchor_ecef = transformers[1].transform(lon, lat, height)
    if not all(np.isfinite(v) for v in anchor_ecef):
        raise PlacementError(
            f'anchor lon={lon} lat={lat} h={height} does not convert to ECEF')

    step = 1.0
    probes = np.array([[east, north, height]] * 6, dtype='float64')
    for axis in range(3):
        probes[2 * axis, axis] += step
        probes[2 * axis + 1, axis] -= step
    local = _projected_block_to_enu(probes, transformers, anchor_ecef,
                                    float(lon), float(lat))
    jacobian = ((local[0::2] - local[1::2]) / (2.0 * step)).T
    if not np.isfinite(jacobian).all():
        raise PlacementError(
            f'{crs} is not differentiable at the anchor {(east, north)}: '
            'the mesh sits on the edge of the projection.')
    u, _singular, vt = np.linalg.svd(jacobian)
    rotation = u @ vt
    horizontal = float(np.linalg.det(jacobian[:2, :2]))
    if np.linalg.det(rotation) <= 0.0 or horizontal <= 0.0:
        raise PlacementError(
            f'{crs} mirrors the ground at the anchor {(east, north)} '
            '(left-handed axes); a mesh in it cannot be rotated into '
            'East-North-Up.')
    return ProjectedFrame(
        crs=crs, anchor=(east, north, height),
        lon=float(lon), lat=float(lat),
        anchor_ecef=tuple(float(v) for v in anchor_ecef),
        rotation=tuple(tuple(float(v) for v in row) for row in rotation),
        convergence_deg=math.degrees(
            math.atan2(rotation[0, 1], rotation[1, 1])),
        grid_per_true_metre=1.0 / math.sqrt(horizontal))


def to_local_enu_from_projected(points_global, frame: ProjectedFrame,
                                chunk: int = ENU_CHUNK):
    """Projected (E, N, Z) -> TRUE local East-North-Up metres about the
    frame's anchor.

    NOT a translation. Grid axes are turned from East / North by the
    meridian convergence and a grid metre is not a true metre, so
    ``points - anchor`` is a mesh rotated about its anchor and mis-scaled
    (BUGS.md B28: 0.48 deg and 0.025 % at NA165/H2060). Every vertex takes
    the reference route instead - grid -> lon / lat by PROJ, its Z as the
    height, geodetic -> ECEF, then the same ECEF -> ENU the geocentric
    route uses - so the two routes hand ion the same mesh for the same
    geometry. Exact for any projection PROJ knows; no small-site
    approximation is involved.

    Chunked: the temporaries are a few columns of ``chunk`` rows.
    """
    import numpy as np

    points = np.asarray(points_global, dtype='float64')
    transformers = _projected_transformers(frame.crs)
    out = np.empty((len(points), 3), dtype='float64')
    for start in range(0, len(points), chunk):
        out[start:start + chunk] = _projected_block_to_enu(
            points[start:start + chunk], transformers, frame.anchor_ecef,
            frame.lon, frame.lat)
    if not np.isfinite(out).all():
        bad = int((~np.isfinite(out).all(axis=1)).sum())
        raise PlacementError(
            f'{bad} of {len(points)} vertices do not convert from '
            f'{frame.crs} to a position on the globe; the mesh is not '
            'inside the projection it declares.')
    return out


def ecef_enu_rotation(lon_deg: float, lat_deg: float):
    """Rows East, North, Up at a point - the ECEF -> ENU rotation.

    Right-handed and orthonormal, so it preserves winding and lengths.
    """
    import numpy as np

    lon = math.radians(lon_deg)
    lat = math.radians(lat_deg)
    sin_lon, cos_lon = math.sin(lon), math.cos(lon)
    sin_lat, cos_lat = math.sin(lat), math.cos(lat)
    return np.array([
        [-sin_lon, cos_lon, 0.0],
        [-sin_lat * cos_lon, -sin_lat * sin_lon, cos_lat],
        [cos_lat * cos_lon, cos_lat * sin_lon, sin_lat],
    ], dtype='float64')


def to_local_enu_from_ecef(points_ecef, anchor_ecef, lon_deg: float,
                           lat_deg: float):
    """ECEF -> local East-North-Up metres about an ECEF anchor.

    This CANNOT be a translation. Subtracting an ECEF anchor leaves a frame
    parallel to ECEF, which at this site is rotated from ENU by the site's
    own latitude and longitude - so the model would arrive standing on its
    side. The rotation is the whole point, and it is why the caller must
    also rotate the OBJ's ``vn`` normals: translation leaves them valid,
    rotation does not. The projected route ends here too
    (:func:`to_local_enu_from_projected`), which is what makes the two
    routes agree.
    """
    import numpy as np

    rot = ecef_enu_rotation(lon_deg, lat_deg)
    delta = np.asarray(points_ecef, dtype='float64') - np.asarray(
        anchor_ecef, dtype='float64')
    return delta @ rot.T, rot


def rewrite_obj_local(src: Path, dst: Path, local_points,
                      normal_rotation=None) -> int:
    """Copy an OBJ, replacing only its ``v`` lines with local coordinates.

    Everything else - ``vt``, ``vn``, ``f``, ``mtllib``, ``usemtl``, groups,
    comments - is passed through byte-for-byte in order, so the material and
    texture bindings that ion needs survive untouched. Six decimals is
    millimetre precision once coordinates are local and small, which is finer
    than the survey itself.

    ``normal_rotation`` is the plan's ``enu_rotation``: the 3x3 that takes
    the export's own axes into ENU at the anchor - ECEF -> ENU for a
    GEOCENTRIC export, grid -> ENU (a turn about Up by the meridian
    convergence) for a PROJECTED one. Both localisations ROTATE, and a
    rotated mesh carrying unrotated ``vn`` lines is lit from the wrong
    direction everywhere. Normals are direction vectors, so they take the
    rotation WITHOUT the translation - and without the grid scale: a
    rotation keeps them unit length. With None the ``vn`` lines pass
    through untouched.
    """
    import numpy as np

    rot = None if normal_rotation is None else np.asarray(
        normal_rotation, dtype='float64')

    written = 0
    normals = 0
    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open('r', encoding='utf-8', errors='replace') as fin, \
            dst.open('w', encoding='utf-8', newline='\n') as fout:
        for line in fin:
            if line.startswith('v '):
                x, y, z = local_points[written]
                fout.write(f'v {x:.6f} {y:.6f} {z:.6f}\n')
                written += 1
            elif rot is not None and line.startswith('vn '):
                parts = line.split()
                vec = np.array([float(parts[1]), float(parts[2]),
                                float(parts[3])], dtype='float64')
                nx, ny, nz = rot @ vec
                fout.write(f'vn {nx:.6f} {ny:.6f} {nz:.6f}\n')
                normals += 1
            else:
                fout.write(line)
    if written != len(local_points):
        raise PlacementError(
            f'{src}: rewrote {written} vertices but was given '
            f'{len(local_points)} - the file changed under us')
    if rot is not None and normals:
        logger.debug('%s: rotated %d vn normals into ENU', src.name, normals)
    return written


def nav_envelope_from_flight_log(path: Path) -> dict:
    """``{'east': (lo, hi), 'north': (lo, hi), 'alt': (lo, hi)}`` from a log.

    Rows whose easting and northing are both zero are the pipeline's
    missing-nav marker and are excluded; including them would stretch the
    envelope to the origin and validate any interpretation at all.
    """
    east: list[float] = []
    north: list[float] = []
    alt: list[float] = []
    with path.open('r', encoding='utf-8', errors='replace') as handle:
        for index, line in enumerate(handle):
            if index == 0:
                continue
            parts = line.rstrip('\n').split(';')
            if len(parts) < 4:
                continue
            try:
                x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
            except ValueError:
                continue
            if x == 0.0 and y == 0.0:
                continue
            east.append(x)
            north.append(y)
            alt.append(z)
    if not east:
        raise PlacementError(f'{path} yielded no usable nav rows')
    return {'east': (min(east), max(east)),
            'north': (min(north), max(north)),
            'alt': (min(alt), max(alt))}


def plan_placement(objs: list[Path], nav_envelope: dict | None = None,
                   geoid_model: str = 'EGM2008',
                   apply_geoid: bool = True):
    """One shared anchor for every OBJ, and each OBJ's local vertices.

    The anchor MUST be common: parts localised about different origins would
    be scattered across the site once ion places each at the same position.
    """
    import numpy as np

    resolved: list[tuple[Path, object]] = []
    crs_seen: set[str] = set()
    geocentric_seen: set[bool] = set()
    interpretations: set[str] = set()

    for obj in objs:
        sidecar = find_rsinfo(obj)
        if sidecar is None:
            raise PlacementError(
                f'no .rsInfo/.rcInfo sidecar beside {obj}. It is the only '
                'record of the export coordinate system; without it the mesh '
                'cannot be placed. Re-export with MvsMeshExportInfoFile=true.')
        info = parse_rsinfo(sidecar)
        # Refused BEFORE the vertices are read: a CRS this module cannot
        # localise from should not cost a 24-million-line parse first.
        if not info.is_geocentric and info.vertex_crs not in crs_seen:
            check_projected_crs(info.vertex_crs)
        crs_seen.add(info.vertex_crs)
        geocentric_seen.add(info.is_geocentric)
        vertices = read_obj_vertices(obj)
        global_points, interpretation = resolve_to_global(
            vertices, info, nav_envelope=nav_envelope)
        interpretations.add(str(interpretation))
        resolved.append((obj, global_points))

    # Checked BEFORE the generic CRS comparison: a geocentric/projected mix
    # also shows up there, but as "EPSG:4978 vs EPSG:32653", which reads
    # like two survey zones rather than two kinds of export.
    if len(geocentric_seen) > 1:
        raise PlacementError(
            'the selected meshes mix geocentric and projected exports '
            '(exportCoordinateSystemType 3 and not-3). They are not in a '
            'common frame and cannot share one anchor; publish them as '
            'separate assets.')
    if len(crs_seen) > 1:
        raise PlacementError(
            f'the selected meshes declare different coordinate systems '
            f'({sorted(crs_seen)}); they cannot share one anchor. Publish '
            'them as separate assets.')
    crs = crs_seen.pop()
    if len(interpretations) > 1:
        raise PlacementError(
            'the selected meshes needed different readings of '
            f'transformToModel ({sorted(interpretations)}), which means they '
            'are not in a common frame. Refusing to place them together.')

    low = np.min([g.min(axis=0) for _, g in resolved], axis=0)
    high = np.max([g.max(axis=0) for _, g in resolved], axis=0)
    anchor = (low + high) / 2.0

    from pyproj import Transformer
    geocentric = geocentric_seen == {True}

    if geocentric:
        # The ECEF vertices convert to lon/lat/height directly - but that
        # height is NOT a true ellipsoidal height in this pipeline. MEASURED
        # 2026-09-28 (NA165/H2060 Component 10): RealityScan builds its ECEF
        # placement from the flight log's Alt column, which geoall.py fills
        # with -depth below the SEA SURFACE, and it puts that number in the
        # ellipsoidal slot unchanged (mesh -649..-645 m, cameras within
        # 3.5 cm of the nav Alt). So the ECEF height is an orthometric depth
        # in disguise and needs exactly the projected branch's correction,
        # h = H + N. Before this fix the geocentric path applied none and
        # placed assets N metres too deep - EGM2008 at each dive's nav
        # centroid: H2060 +25.2, H2063 +25.2, H2077 +65.9, H2080 +72.7,
        # H2082 +71.0 m.
        to_geo3 = Transformer.from_crs('EPSG:4978', 'EPSG:4979',
                                       always_xy=True)
        lon, lat, ecef_h = to_geo3.transform(
            float(anchor[0]), float(anchor[1]), float(anchor[2]))
        if not all(np.isfinite(v) for v in (lon, lat, ecef_h)):
            raise PlacementError(
                f'anchor ECEF {anchor} does not convert to lon/lat/height')
        if apply_geoid:
            ell_h, separation = msl_to_ellipsoidal(
                float(ecef_h), float(lon), float(lat), geoid_model)
            model_used = geoid_model
        else:
            ell_h, separation, model_used = float(ecef_h), 0.0, 'NONE'
            logger.warning(
                'GEOID CORRECTION DISABLED (--no-geoid) for a geocentric '
                'export: its height is the flight log\'s -depth, so the '
                'asset will sit the local geoid undulation too deep.')
        rot = ecef_enu_rotation(float(lon), float(lat))
        localised = [(obj, to_local_enu_from_ecef(
            g, anchor, float(lon), float(lat))[0]) for obj, g in resolved]
        extent_pts = np.vstack([g for _, g in localised])
        extent = tuple(float(v) for v in
                       (extent_pts.max(axis=0) - extent_pts.min(axis=0)))
        logger.info('geocentric export (exportCoordinateSystemType=3): '
                    'vertices read as EPSG:4978 and rotated into ENU about '
                    'the anchor. The declared CRS describes the PROJECT, '
                    'not these vertices.')
        plan = {
            'crs': 'EPSG:4978',
            'geocentric': True,
            'enu_rotation': [list(r) for r in rot],
            'interpretation': interpretations.pop(),
            'anchor_projected': [float(anchor[0]), float(anchor[1]),
                                 float(anchor[2])],
            'lon': float(lon), 'lat': float(lat),
            'height_ellipsoidal_m': float(ell_h),
            'ecef_height_m': float(ecef_h),
            'depth_msl_m': float(ecef_h),
            'geoid_n_m': float(separation),
            'geoid_model': model_used,
            'extent_m': list(extent),
            'vertex_count': int(sum(len(g) for _, g in resolved)),
            'files': [str(o) for o, _ in resolved],
        }
        return plan, localised

    # The anchor is what it always was - the midpoint of the mesh's bounding
    # box in the export's own CRS, converted by the same transformer - so
    # the position ion is given does not move. What changed (B28) is the
    # mesh handed over with it.
    depth_msl = float(anchor[2])
    frame = projected_frame(crs, (float(anchor[0]), float(anchor[1]),
                                  depth_msl))
    lon, lat = frame.lon, frame.lat

    if apply_geoid:
        height, separation = msl_to_ellipsoidal(
            depth_msl, float(lon), float(lat), geoid_model)
        model_used = geoid_model
    else:
        height, separation, model_used = depth_msl, 0.0, 'NONE'
        logger.warning(
            'GEOID CORRECTION DISABLED (--no-geoid). The mesh Z is a depth '
            'below the SEA SURFACE but ion will read it as a height above the '
            'WGS84 ELLIPSOID. The asset will be wrong by the local geoid '
            'undulation - measured at +4.5 m at Papahanaumokuakea, +15.9 m at '
            'Oahu, -27.1 m in the Gulf of Mexico, +25.2 m at NA165/H2060 and '
            '+72.7 m at NA168/H2080. Use this only for a deliberately '
            'local-frame asset.')

    # Each part goes to true ENU about the shared anchor and its grid copy is
    # dropped as soon as it has, so the component is never held in both
    # frames at once - only the part in hand is.
    vertex_count = int(sum(len(g) for _, g in resolved))
    files = [str(o) for o, _ in resolved]
    localised = []
    local_low = local_high = None
    for index, (obj, global_points) in enumerate(resolved):
        local = to_local_enu_from_projected(global_points, frame)
        resolved[index] = (obj, None)
        localised.append((obj, local))
        part_low, part_high = local.min(axis=0), local.max(axis=0)
        local_low = part_low if local_low is None else np.minimum(
            local_low, part_low)
        local_high = part_high if local_high is None else np.maximum(
            local_high, part_high)
    # East x North x Up of what is uploaded - the axes ion's tight box is
    # in, which is what --verify compares this against.
    extent = tuple(float(v) for v in (local_high - local_low))
    logger.info('projected export: vertices taken %s -> geodetic -> ECEF '
                'and rotated into true ENU about the anchor. Grid north is '
                '%+.4f deg from true north there and a true metre is %.6f '
                'grid metres.', crs, frame.convergence_deg,
                frame.grid_per_true_metre)

    plan = {
        'crs': crs,
        'interpretation': interpretations.pop(),
        'enu_rotation': [list(row) for row in frame.rotation],
        'grid_convergence_deg': frame.convergence_deg,
        'grid_per_true_metre': frame.grid_per_true_metre,
        'anchor_projected': [float(anchor[0]), float(anchor[1]), depth_msl],
        'lon': float(lon), 'lat': float(lat),
        'height_ellipsoidal_m': float(height),
        'depth_msl_m': depth_msl,
        'geoid_n_m': float(separation),
        'geoid_model': model_used,
        'extent_m': list(extent),
        'vertex_count': vertex_count,
        'files': files,
    }
    return plan, localised
