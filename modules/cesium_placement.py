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

Two further traps, both found the expensive way and both guarded here:

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

    crs = info.crs
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

def to_local_enu(points_global, anchor_en: tuple[float, float],
                 anchor_z: float):
    """Global (E, N, Z) -> local East-North-Up metres about an anchor.

    A projected CRS is already metric and axis-aligned with ENU to well
    within a metre over a site a few hundred metres across, so this is a
    translation. Keeping it a pure translation matters: it leaves normals,
    winding and texture coordinates untouched, so only the ``v`` lines of the
    OBJ change.
    """
    import numpy as np

    offset = np.array([anchor_en[0], anchor_en[1], anchor_z], dtype='float64')
    return points_global - offset


def rewrite_obj_local(src: Path, dst: Path, local_points) -> int:
    """Copy an OBJ, replacing only its ``v`` lines with local coordinates.

    Everything else - ``vt``, ``vn``, ``f``, ``mtllib``, ``usemtl``, groups,
    comments - is passed through byte-for-byte in order, so the material and
    texture bindings that ion needs survive untouched. Six decimals is
    millimetre precision once coordinates are local and small, which is finer
    than the survey itself.
    """
    written = 0
    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open('r', encoding='utf-8', errors='replace') as fin, \
            dst.open('w', encoding='utf-8', newline='\n') as fout:
        for line in fin:
            if line.startswith('v '):
                x, y, z = local_points[written]
                fout.write(f'v {x:.6f} {y:.6f} {z:.6f}\n')
                written += 1
            else:
                fout.write(line)
    if written != len(local_points):
        raise PlacementError(
            f'{src}: rewrote {written} vertices but was given '
            f'{len(local_points)} - the file changed under us')
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
    interpretations: set[str] = set()

    for obj in objs:
        sidecar = find_rsinfo(obj)
        if sidecar is None:
            raise PlacementError(
                f'no .rsInfo/.rcInfo sidecar beside {obj}. It is the only '
                'record of the export coordinate system; without it the mesh '
                'cannot be placed. Re-export with MvsMeshExportInfoFile=true.')
        info = parse_rsinfo(sidecar)
        crs_seen.add(info.crs)
        vertices = read_obj_vertices(obj)
        global_points, interpretation = resolve_to_global(
            vertices, info, nav_envelope=nav_envelope)
        interpretations.add(str(interpretation))
        resolved.append((obj, global_points))

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
    to_geo = Transformer.from_crs(crs, 'EPSG:4326', always_xy=True)
    lon, lat = to_geo.transform(float(anchor[0]), float(anchor[1]))
    if not (np.isfinite(lon) and np.isfinite(lat)):
        raise PlacementError(
            f'anchor easting/northing {anchor[:2]} does not convert to '
            f'lon/lat under {crs}')

    depth_msl = float(anchor[2])
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
            'Oahu, -27.1 m in the Gulf of Mexico and +72.7 m at this repo''s '
            'NA168 site. Use this only for a deliberately local-frame asset.')

    localised = [(obj, to_local_enu(g, (float(anchor[0]), float(anchor[1])),
                                    depth_msl))
                 for obj, g in resolved]
    extent = tuple(float(v) for v in (high - low))

    plan = {
        'crs': crs,
        'interpretation': interpretations.pop(),
        'anchor_projected': [float(anchor[0]), float(anchor[1]), depth_msl],
        'lon': float(lon), 'lat': float(lat),
        'height_ellipsoidal_m': float(height),
        'depth_msl_m': depth_msl,
        'geoid_n_m': float(separation),
        'geoid_model': model_used,
        'extent_m': list(extent),
        'vertex_count': int(sum(len(g) for _, g in resolved)),
        'files': [str(o) for o, _ in resolved],
    }
    return plan, localised
