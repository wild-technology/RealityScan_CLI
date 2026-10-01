"""A projected export reaches ion in TRUE East-North-Up - BUGS.md B28.

Traced to the nav-placed NA165/H2060 products (2026-10-01). They are type-0
exports in EPSG:32702 with Z = -depth, and the projected route localised
them by subtracting the anchor: the staged vertices equalled the product's
minus the anchor to 1.6e-9 m. A UTM grid is not East-North-Up. The site is
210 km from the central meridian of zone 2S, where grid north is 0.4797 deg
from true north and a true metre is 1.000251 grid metres (1.000149 from the
projection, the rest from the mesh being 650 m below the ellipsoid), so
every projected upload was turned about its anchor and mis-scaled - 0.064 m
at the far corner of Component 10, 0.24 m on Component 9 - while the
geocentric route, given the same geometry as ECEF, was not.

These pin that both routes now hand ion the SAME local mesh for the same
geometry, that the anchor did not move, that the ``vn`` normals turn with
the vertices, and which CRS kinds are localised and which are refused.

Every expected number is derived here, from PROJ and from closed forms
written out below (geodetic -> ECEF, the East-North-Up basis). Nothing is
taken from the module under test, so a wrong turn there cannot agree with
itself. Hermetic: no network, no geoid grid (N is stubbed), no RealityScan.
"""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

np = pytest.importorskip("numpy")
pyproj = pytest.importorskip("pyproj")

from modules import cesium_placement as cp  # noqa: E402
from modules.cesium_placement import (  # noqa: E402
    PlacementError, check_projected_crs, plan_placement, projected_frame,
    read_obj_vertices, to_local_enu_from_projected)

# The NA165/H2060 site, and the -depth RealityScan carries in the height slot.
SITE_LON, SITE_LAT, SITE_Z = -169.047, -14.212, -650.0
UTM_2S = "EPSG:32702"
STUB_N = 25.25

PROJECTED_SIDECAR = (
    '<Model globalCoordinateSystem="%s" globalCoordinateSystemName="%s" '
    'exportCoordinateSystemType="0"/>\n')
GEOCENTRIC_SIDECAR = (
    '<Model globalCoordinateSystem="+proj=utm +zone=2 +south +datum=WGS84 '
    '+units=m +no_defs" '
    'globalCoordinateSystemName="epsg:32702 - WGS 84 / UTM zone 2S" '
    'exportCoordinateSystemType="3" '
    'transformToModel="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>\n')

# A true-scale transverse Mercator whose central meridian runs through the
# site: on it, at the ellipsoid, a grid IS East-North-Up.
TMERC_ON_SITE = ("+proj=tmerc +lat_0=0 +lon_0=%s +k=1 +x_0=500000 "
                 "+y_0=10000000 +datum=WGS84 +units=m +no_defs" % SITE_LON)


# ------------------------------------------- the independent reference

def wgs84():
    ellipsoid = pyproj.CRS("EPSG:4326").ellipsoid
    a = ellipsoid.semi_major_metre
    f = 1.0 / ellipsoid.inverse_flattening
    return a, f * (2.0 - f)                          # a, e squared


def geodetic_to_ecef(lon_deg, lat_deg, h):
    """Closed form, written out - not the module's, not PROJ's."""
    a, e2 = wgs84()
    lon, lat = np.radians(lon_deg), np.radians(lat_deg)
    prime = a / np.sqrt(1.0 - e2 * np.sin(lat) ** 2)
    return np.stack([(prime + h) * np.cos(lat) * np.cos(lon),
                     (prime + h) * np.cos(lat) * np.sin(lon),
                     (prime * (1.0 - e2) + h) * np.sin(lat)], axis=-1)


def enu_basis(lon_deg, lat_deg):
    """Rows East, North, Up in ECEF at a point."""
    lon, lat = math.radians(lon_deg), math.radians(lat_deg)
    return np.array([
        [-math.sin(lon), math.cos(lon), 0.0],
        [-math.sin(lat) * math.cos(lon), -math.sin(lat) * math.sin(lon),
         math.cos(lat)],
        [math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon),
         math.sin(lat)]])


def reference_enu(verts, anchor, crs):
    """Where (E, N, Z) rows sit in true ENU about an (E, N, Z) anchor: the
    grid undone by PROJ, then this file's own ECEF and basis."""
    verts = np.asarray(verts, dtype="float64")
    to_geo = pyproj.Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    lon, lat = to_geo.transform(verts[:, 0], verts[:, 1])
    lon0, lat0 = to_geo.transform(anchor[0], anchor[1])
    delta = (geodetic_to_ecef(lon, lat, verts[:, 2])
             - geodetic_to_ecef(lon0, lat0, anchor[2]))
    return delta @ enu_basis(lon0, lat0).T


def grid_turn(crs, lon, lat):
    """(grid -> ENU rotation, convergence in degrees, projection scale k)
    from PROJ's own factors. Grid north lies at azimuth gamma, clockwise
    from true north, so grid east is (cos g, -sin g) and grid north
    (sin g, cos g) in East / North."""
    factors = pyproj.Proj(crs).get_factors(lon, lat)
    gamma = math.radians(factors.meridian_convergence)
    turn = np.array([[math.cos(gamma), math.sin(gamma), 0.0],
                     [-math.sin(gamma), math.cos(gamma), 0.0],
                     [0.0, 0.0, 1.0]])
    return turn, factors.meridian_convergence, factors.meridional_scale


def height_factor(lat_deg, h):
    """True metres per ellipsoid metre at height h: (R + h) / R, with R the
    prime-vertical radius. A mesh at depth is smaller than its footprint on
    the ellipsoid; 1.02e-4 of it at -650 m."""
    a, e2 = wgs84()
    prime = a / math.sqrt(1.0 - e2 * math.sin(math.radians(lat_deg)) ** 2)
    return 1.0 + h / prime


def site_grid(crs, lon=SITE_LON, lat=SITE_LAT):
    """A site's easting and northing, to the millimetre - so that a vertex
    written to an OBJ at six decimals reads back as the same float and the
    anchor the plan finds is the anchor the test meant."""
    forward = pyproj.Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    east, north = forward.transform(lon, lat)
    return round(east, 3), round(north, 3)


# ------------------------------------------------------------- fixtures

def write_obj(folder, name, verts, normals=(), sidecar=None):
    folder.mkdir(parents=True, exist_ok=True)
    lines = ["# test", "mtllib none.mtl"]
    lines += ["v %.6f %.6f %.6f" % tuple(v) for v in verts]
    lines += ["vn %.9f %.9f %.9f" % tuple(n) for n in normals]
    lines.append("f 1//1 2//1 3//1")
    path = folder / (name + ".obj")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if sidecar is not None:
        (folder / (name + ".obj.rsInfo")).write_text(sidecar, encoding="utf-8")
    return path


def projected_sidecar(crs=UTM_2S):
    if crs.upper().startswith("EPSG:"):
        return PROJECTED_SIDECAR % ("", "epsg:%s - test" % crs.split(":")[1])
    return PROJECTED_SIDECAR % (crs, "")


def staged_normals(path):
    return np.array([[float(x) for x in line.split()[1:4]]
                     for line in path.read_text(encoding="utf-8").splitlines()
                     if line.startswith("vn ")])


def stub_geoid(monkeypatch, value=STUB_N):
    monkeypatch.setattr(cp, "geoid_separation",
                        lambda lon, lat, model="EGM2008": value)


def cross(east, north, z, reach=50.0):
    """Five vertices whose bounding-box midpoint is exactly (east, north, z):
    the anchor, +-reach along grid east, +-20 m along grid north (and +-3 m
    in Z, so the box has a height)."""
    return [(east, north, z), (east + reach, north, z),
            (east - reach, north, z), (east, north + 20.0, z + 3.0),
            (east, north - 20.0, z - 3.0)]


# ------------------------------------- (1) the two routes agree

def box_geometry():
    """The same geometry for both routes: the eight corners of a 40 x 24 x
    10 m box about the site in TRUE East-North-Up, three points inside it,
    and one unit normal per vertex."""
    corners = [(e, n, u) for e in (-20.0, 20.0) for n in (-12.0, 12.0)
               for u in (-5.0, 5.0)]
    local = np.array(corners + [(3.0, -7.0, 1.5), (-11.0, 4.0, -2.0),
                                (0.0, 0.0, 0.0)])
    rng = np.random.default_rng(28)
    normals = rng.normal(size=(len(local), 3))
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    normals[0] = (0.0, 0.0, 1.0)                       # straight Up
    normals[1] = (0.0, 1.0, 0.0)                       # true North
    return local, normals


def both_exports(tmp_path, local, normals_enu):
    """One geometry, written as RealityScan would write each export type:
    ECEF vertices and normals (type 3), and EPSG:32702 eastings / northings
    with the height in Z and the normals in grid axes (type 0)."""
    basis = enu_basis(SITE_LON, SITE_LAT)
    ecef = geodetic_to_ecef(SITE_LON, SITE_LAT, SITE_Z) + local @ basis
    normals_ecef = normals_enu @ basis

    to_geodetic = pyproj.Transformer.from_crs("EPSG:4978", "EPSG:4979",
                                              always_xy=True)
    lon, lat, h = to_geodetic.transform(ecef[:, 0], ecef[:, 1], ecef[:, 2])
    east, north = pyproj.Transformer.from_crs(
        "EPSG:4326", UTM_2S, always_xy=True).transform(lon, lat)
    grid = np.c_[east, north, h]
    turn, _gamma, _k = grid_turn(UTM_2S, SITE_LON, SITE_LAT)
    normals_grid = normals_enu @ turn        # the inverse turn: grid = T' enu

    geocentric = write_obj(tmp_path / "ecef", "m", ecef, normals_ecef,
                           GEOCENTRIC_SIDECAR)
    projected = write_obj(tmp_path / "utm", "m", grid, normals_grid,
                          projected_sidecar())
    return geocentric, projected, ecef


def test_the_same_geometry_reaches_ion_the_same_by_either_route(
        tmp_path, monkeypatch):
    """Vertices to 1 mm, normals to 1e-6, and one plan position. Before the
    fix the projected mesh was the geocentric one turned 0.48 deg: 0.19 m
    apart at the box's corners."""
    from publish_cesium import stage
    stub_geoid(monkeypatch)
    local, normals = box_geometry()
    geocentric, projected, _ecef = both_exports(tmp_path, local, normals)

    plan_g, loc_g = plan_placement([geocentric])
    plan_p, loc_p = plan_placement([projected])
    assert plan_g.get("geocentric") is True and not plan_p.get("geocentric")

    # the same place: 2e-9 deg is 0.2 mm; both carry exactly one N
    assert abs(plan_p["lon"] - plan_g["lon"]) < 2e-9
    assert abs(plan_p["lat"] - plan_g["lat"]) < 2e-9
    assert abs(plan_p["height_ellipsoidal_m"]
               - plan_g["height_ellipsoidal_m"]) < 1e-3
    assert abs(plan_p["lon"] - SITE_LON) < 2e-9
    assert abs(plan_p["lat"] - SITE_LAT) < 2e-9
    assert plan_p["height_ellipsoidal_m"] == pytest.approx(SITE_Z + STUB_N,
                                                           abs=1e-3)
    assert plan_p["geoid_n_m"] == plan_g["geoid_n_m"] == STUB_N

    # the same mesh - and it is the geometry that was written
    assert np.abs(loc_p[0][1] - loc_g[0][1]).max() < 1e-3
    assert np.abs(loc_p[0][1] - local).max() < 1e-3
    assert np.abs(loc_g[0][1] - local).max() < 1e-3
    assert plan_p["extent_m"] == pytest.approx(plan_g["extent_m"], abs=1e-3)
    assert plan_p["extent_m"] == pytest.approx([40.0, 24.0, 10.0], abs=1e-3)

    # the same normals in the files that are uploaded
    staged_g = stage(loc_g, tmp_path / "stage_g", [geocentric],
                     normal_rotation=plan_g.get("enu_rotation"))
    staged_p = stage(loc_p, tmp_path / "stage_p", [projected],
                     normal_rotation=plan_p.get("enu_rotation"))
    (obj_g,) = [p for p in staged_g if p.suffix == ".obj"]
    (obj_p,) = [p for p in staged_p if p.suffix == ".obj"]
    vn_g, vn_p = staged_normals(obj_g), staged_normals(obj_p)
    assert len(vn_g) == len(vn_p) == len(normals)
    assert np.abs(vn_g - normals).max() < 1e-6
    assert np.abs(vn_p - normals).max() < 1e-6
    assert np.abs(read_obj_vertices(obj_p)
                  - read_obj_vertices(obj_g)).max() < 1e-3


def test_both_routes_put_every_vertex_back_where_it_was_on_the_globe(
        tmp_path, monkeypatch):
    """A lopsided 300 m site, so the two bounding-box midpoints - one taken
    in ECEF axes, one in grid axes - are metres apart and the local meshes
    are NOT comparable row by row. What must agree is the globe: each
    route's own anchor plus its own local mesh, carried back to ECEF, is
    the vertex that was exported, to a millimetre."""
    stub_geoid(monkeypatch)
    rng = np.random.default_rng(165)
    local = np.c_[rng.uniform(-150.0, 90.0, 400),
                  rng.uniform(-40.0, 160.0, 400),
                  rng.uniform(-12.0, 3.0, 400)]
    normals = np.tile([0.0, 0.0, 1.0], (len(local), 1))
    geocentric, projected, ecef = both_exports(tmp_path, local, normals)

    anchors = []
    for export in (geocentric, projected):
        plan, localised = plan_placement([export])
        # the mesh hangs off the anchor BEFORE the geoid is added to it
        origin = geodetic_to_ecef(plan["lon"], plan["lat"],
                                  plan["depth_msl_m"])
        back = origin + localised[0][1] @ enu_basis(plan["lon"], plan["lat"])
        assert np.abs(back - ecef).max() < 1e-3
        anchors.append(origin)
    assert np.linalg.norm(anchors[0] - anchors[1]) > 1.0     # and yet


# --------------------------- (2) turned by the convergence, shortened by k

@pytest.mark.parametrize("crs, lon, lat", [
    (UTM_2S, SITE_LON, SITE_LAT),              # H2060: east of -171, south
    ("EPSG:32602", SITE_LON, -SITE_LAT),       # its mirror north of the equator
    (UTM_2S, -172.953, SITE_LAT),              # west of the central meridian
])
def test_a_grid_east_offset_is_turned_by_convergence_and_shortened_by_scale(
        tmp_path, monkeypatch, crs, lon, lat):
    """50 m along grid east is NOT 50 m East. Grid north is at azimuth
    gamma, so grid east is (cos g, -sin g); a grid metre is 1 / k of an
    ellipsoid metre; and at -650 m an ellipsoid metre is (1 + h / R) of a
    true one. All three from PROJ's factors and the ellipsoid, here."""
    stub_geoid(monkeypatch)
    east, north = site_grid(crs, lon, lat)
    obj = write_obj(tmp_path, "m", cross(east, north, SITE_Z),
                    sidecar=projected_sidecar(crs))
    plan, localised = plan_placement([obj])
    got = localised[0][1][1]                    # the +50 m grid-east vertex

    _turn, gamma_deg, k = grid_turn(crs, lon, lat)
    gamma = math.radians(gamma_deg)
    true_length = 50.0 * height_factor(lat, SITE_Z) / k
    expected = (true_length * math.cos(gamma), -true_length * math.sin(gamma))
    assert got[0] == pytest.approx(expected[0], abs=2e-4)
    assert got[1] == pytest.approx(expected[1], abs=2e-4)
    # level on the grid is level on the ground, less the Earth's curve
    assert got[2] == pytest.approx(-true_length ** 2 / (2 * 6.38e6), abs=1e-5)

    # the size of it, so a formula wrong on both sides cannot pass: the
    # site is 1.953 deg of longitude from its central meridian
    assert abs(gamma_deg) == pytest.approx(0.4797, abs=1e-4)
    assert k == pytest.approx(1.000149, abs=1e-6)
    assert abs(got[1]) == pytest.approx(0.4185, abs=1e-4)      # 42 cm sideways
    assert 50.0 - got[0] == pytest.approx(0.0143, abs=2e-4)    # 14 mm short
    # ... and the hand of it: counter-clockwise where gamma is negative
    assert (got[1] > 0) == (gamma_deg < 0)

    # an independent second opinion that never touches the projection's
    # convergence: the geodesic from the anchor to the vertex, scaled to
    # the mesh's depth
    to_geo = pyproj.Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    lon0, lat0 = to_geo.transform(east, north)
    lon1, lat1 = to_geo.transform(east + 50.0, north)
    azimuth, _back, distance = pyproj.Geod(ellps="WGS84").inv(lon0, lat0,
                                                              lon1, lat1)
    reach = distance * height_factor(lat, SITE_Z)
    assert got[0] == pytest.approx(reach * math.sin(math.radians(azimuth)),
                                   abs=2e-4)
    assert got[1] == pytest.approx(reach * math.cos(math.radians(azimuth)),
                                   abs=2e-4)

    assert plan["grid_convergence_deg"] == pytest.approx(gamma_deg, abs=1e-6)
    # (the mean of the east-west and north-south scales, whose radii of
    # curvature differ by 0.6 %: hence 1e-6 and not better)
    assert plan["grid_per_true_metre"] == pytest.approx(
        k / height_factor(lat, SITE_Z), abs=1e-6)
    # every vertex, against the reference route
    assert np.abs(localised[0][1] - reference_enu(
        cross(east, north, SITE_Z), (east, north, SITE_Z), crs)).max() < 1e-6


def test_distances_are_true_distances(tmp_path, monkeypatch):
    """The localised mesh is metric: two vertices are as far apart as the
    straight line between them through the Earth, not as far as the grid
    says (2.5 cm more per 100 m here)."""
    stub_geoid(monkeypatch)
    east, north = site_grid(UTM_2S)
    verts = cross(east, north, SITE_Z, reach=100.0)
    obj = write_obj(tmp_path, "m", verts, sidecar=projected_sidecar())
    _plan, localised = plan_placement([obj])
    local = localised[0][1]

    to_geo = pyproj.Transformer.from_crs(UTM_2S, "EPSG:4326", always_xy=True)
    grid = np.array(verts)
    lon, lat = to_geo.transform(grid[:, 0], grid[:, 1])
    ecef = geodetic_to_ecef(lon, lat, grid[:, 2])
    for i, j in ((1, 2), (3, 4), (1, 3)):
        chord = np.linalg.norm(ecef[i] - ecef[j])
        assert np.linalg.norm(local[i] - local[j]) == pytest.approx(chord,
                                                                    abs=1e-6)
    grid_length = np.linalg.norm(grid[1] - grid[2])
    assert grid_length == 200.0
    assert grid_length - np.linalg.norm(local[1] - local[2]) == pytest.approx(
        0.0503, abs=2e-4)


# --------------------------------------------- (3) on a central meridian

def test_on_the_meridian_of_a_true_scale_grid_it_is_the_old_translation(
        tmp_path, monkeypatch):
    """Where a grid really is East-North-Up - on the central meridian of a
    k = 1 transverse Mercator, at the ellipsoid - the fix changes nothing:
    the mesh is the vertices minus the anchor to a tenth of a millimetre
    (what is left is the Earth's curve over 25 m: 0.05 mm)."""
    stub_geoid(monkeypatch)
    east, north = site_grid(TMERC_ON_SITE)
    assert east == pytest.approx(500000.0, abs=1e-6)
    verts = [(east, north, 0.0),
             (east + 20.0, north + 15.0, 2.0), (east - 20.0, north - 15.0, -2.0),
             (east + 20.0, north - 15.0, 1.0), (east - 20.0, north + 15.0, -1.0)]
    obj = write_obj(tmp_path, "m", verts,
                    sidecar=projected_sidecar(TMERC_ON_SITE))
    plan, localised = plan_placement([obj])

    translation = np.array(verts) - np.array([east, north, 0.0])
    assert np.abs(localised[0][1] - translation).max() < 1e-4
    assert np.abs(np.array(plan["enu_rotation"]) - np.eye(3)).max() < 1e-9
    assert abs(plan["grid_convergence_deg"]) < 1e-7
    assert plan["grid_per_true_metre"] == pytest.approx(1.0, abs=1e-8)
    assert plan["extent_m"] == pytest.approx([40.0, 30.0, 4.0], abs=1e-4)


def test_on_a_utm_central_meridian_there_is_no_turn_only_the_scale(
        tmp_path, monkeypatch):
    """UTM is not true-scale on its own meridian: k = 0.9996 there, so the
    old translation was already 20 mm short per 50 m. No rotation, though -
    a grid-east offset stays due East."""
    stub_geoid(monkeypatch)
    east, north = site_grid(UTM_2S, -171.0, SITE_LAT)
    assert east == pytest.approx(500000.0, abs=1e-6)
    obj = write_obj(tmp_path, "m", cross(east, north, SITE_Z),
                    sidecar=projected_sidecar())
    plan, localised = plan_placement([obj])
    got = localised[0][1][1]

    _turn, gamma_deg, k = grid_turn(UTM_2S, -171.0, SITE_LAT)
    assert abs(gamma_deg) < 1e-9 and k == pytest.approx(0.9996, abs=1e-9)
    assert got[0] == pytest.approx(
        50.0 * height_factor(SITE_LAT, SITE_Z) / k, abs=2e-4)
    assert got[0] == pytest.approx(50.0149, abs=2e-4)
    assert abs(got[1]) < 1e-6
    assert np.abs(np.array(plan["enu_rotation"]) - np.eye(3)).max() < 1e-9
    assert abs(plan["grid_convergence_deg"]) < 1e-7


# ------------------------------------------------------------ (4) normals

def test_normals_turn_with_the_mesh_and_stay_unit(tmp_path, monkeypatch):
    """A rotated mesh carrying unrotated normals is lit from the wrong
    direction. The ``vn`` lines take the same turn as the vertices - and
    only the turn: no scale, so they stay unit length."""
    from publish_cesium import stage
    stub_geoid(monkeypatch)
    east, north = site_grid(UTM_2S)
    tilted = np.array([1.0, 2.0, 2.0]) / 3.0
    normals = [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0),
               tuple(tilted)]
    obj = write_obj(tmp_path / "export", "m", cross(east, north, SITE_Z),
                    normals, projected_sidecar())
    plan, localised = plan_placement([obj])
    staged = stage(localised, tmp_path / "staging", [obj],
                   normal_rotation=plan.get("enu_rotation"))
    (staged_obj,) = [p for p in staged if p.suffix == ".obj"]
    got = staged_normals(staged_obj)

    turn, gamma_deg, _k = grid_turn(UTM_2S, SITE_LON, SITE_LAT)
    gamma = math.radians(gamma_deg)
    assert np.abs(got - np.array(normals) @ turn.T).max() < 1e-6
    assert got[0] == pytest.approx([math.cos(gamma), -math.sin(gamma), 0.0],
                                   abs=1e-6)
    assert got[1] == pytest.approx([math.sin(gamma), math.cos(gamma), 0.0],
                                   abs=1e-6)
    assert got[2] == pytest.approx([0.0, 0.0, 1.0], abs=1e-6)   # Up stays Up
    assert np.abs(np.linalg.norm(got, axis=1) - 1.0).max() < 1e-6
    assert abs(got[1][0]) > 8e-3            # 0.48 deg is not nothing

    # WITH the mesh: the grid-east normal points along the grid-east edge
    edge = read_obj_vertices(staged_obj)[1]
    assert got[0] == pytest.approx(edge / np.linalg.norm(edge), abs=1e-5)

    rotation = np.array(plan["enu_rotation"])
    assert np.allclose(rotation @ rotation.T, np.eye(3), atol=1e-12)
    assert np.linalg.det(rotation) == pytest.approx(1.0, abs=1e-12)
    assert np.abs(rotation - turn).max() < 1e-8


# ----------------------------- (5) the anchor, and the geoid on it alone

def test_the_anchor_does_not_move(tmp_path, monkeypatch):
    """The fix changes the mesh, not where ion is told to put it: the
    anchor is still the midpoint of the bounding box in the export's own
    CRS, converted as it always was, with one N on its height."""
    stub_geoid(monkeypatch)
    east, north = 710830.0, 8428136.0
    verts = [(east - 5.0, north - 6.0, -652.0),
             (east + 5.0, north + 6.0, -648.0),
             (east + 1.0, north - 2.0, -649.0)]
    obj = write_obj(tmp_path, "m", verts, sidecar=projected_sidecar())
    plan, localised = plan_placement([obj])

    assert plan["anchor_projected"] == [east, north, -650.0]
    lon, lat = pyproj.Transformer.from_crs(
        UTM_2S, "EPSG:4326", always_xy=True).transform(east, north)
    assert plan["lon"] == pytest.approx(lon, abs=1e-12)
    assert plan["lat"] == pytest.approx(lat, abs=1e-12)
    assert plan["depth_msl_m"] == -650.0
    assert plan["height_ellipsoidal_m"] == -650.0 + STUB_N
    # a vertex AT the anchor would be the local origin: the frame is
    # centred on the position ion is given
    frame = projected_frame(UTM_2S, (east, north, -650.0))
    assert (frame.lon, frame.lat) == (plan["lon"], plan["lat"])
    origin = to_local_enu_from_projected(
        np.array([[east, north, -650.0]]), frame)
    assert np.abs(origin).max() < 1e-9
    assert np.abs(localised[0][1] - reference_enu(
        verts, (east, north, -650.0), UTM_2S)).max() < 1e-6


def test_the_geoid_is_on_the_anchor_and_not_in_the_staged_mesh(
        tmp_path, monkeypatch):
    """--no-geoid changes one number, the height in the request. The
    staged OBJ - vertices AND normals - is the same file byte for byte,
    for a positive undulation and a negative one."""
    from publish_cesium import stage
    east, north = site_grid(UTM_2S)
    obj = write_obj(tmp_path / "export", "m", cross(east, north, SITE_Z),
                    [(0.6, 0.0, 0.8)], projected_sidecar())
    staged_bytes, heights = [], []
    for label, undulation in (("plus", STUB_N), ("minus", -27.0),
                              ("none", None)):
        stub_geoid(monkeypatch, undulation)
        plan, localised = plan_placement([obj],
                                         apply_geoid=undulation is not None)
        staged = stage(localised, tmp_path / label, [obj],
                       normal_rotation=plan.get("enu_rotation"))
        (staged_obj,) = [p for p in staged if p.suffix == ".obj"]
        staged_bytes.append(staged_obj.read_bytes())
        heights.append(plan["height_ellipsoidal_m"])
    assert staged_bytes[0] == staged_bytes[1] == staged_bytes[2]
    assert heights == [SITE_Z + STUB_N, SITE_Z - 27.0, SITE_Z]


# ----------------------------------------------- chunking, and the edges

def test_localisation_is_chunked_and_the_chunks_agree(monkeypatch):
    """A 24-million-vertex component must not go to PROJ in one call. Any
    chunk size gives the same answer, and no block is larger than asked."""
    east, north = site_grid(UTM_2S)
    frame = projected_frame(UTM_2S, (east, north, SITE_Z))
    rng = np.random.default_rng(9)
    points = np.c_[east + rng.uniform(-100, 100, 1000),
                   north + rng.uniform(-100, 100, 1000),
                   SITE_Z + rng.uniform(-5, 5, 1000)]
    whole = to_local_enu_from_projected(points, frame)

    seen = []
    real = cp._projected_block_to_enu

    def spy(block, *args):
        seen.append(len(block))
        return real(block, *args)

    monkeypatch.setattr(cp, "_projected_block_to_enu", spy)
    pieces = to_local_enu_from_projected(points, frame, chunk=64)
    assert seen == [64] * 15 + [40]
    assert np.array_equal(pieces, whole)
    assert np.abs(whole - reference_enu(points, (east, north, SITE_Z),
                                        UTM_2S)).max() < 1e-6
    assert cp.ENU_CHUNK <= 1 << 21              # the default stays bounded


def test_a_lone_vertex_goes_to_proj_as_an_array_not_through_float():
    """PROJ's point shortcut takes a one-element array through float(),
    which NumPy has deprecated (1.25) and newer NumPy refuses. A block of
    one vertex - a one-vertex OBJ, or the last block of a mesh of
    chunk x n + 1 - must not depend on it."""
    import warnings
    east, north = site_grid(UTM_2S)
    frame = projected_frame(UTM_2S, (east, north, SITE_Z))
    points = np.array([[east + 50.0, north, SITE_Z],
                       [east, north + 20.0, SITE_Z + 3.0],
                       [east - 7.0, north - 9.0, SITE_Z - 1.0]])
    whole = to_local_enu_from_projected(points, frame)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        alone = to_local_enu_from_projected(points[:1], frame)
        tail = to_local_enu_from_projected(points, frame, chunk=2)
    assert alone.shape == (1, 3)
    assert np.array_equal(alone, whole[:1])
    assert np.array_equal(tail, whole)


def test_a_vertex_outside_the_projection_is_refused_not_placed():
    east, north = site_grid(UTM_2S)
    frame = projected_frame(UTM_2S, (east, north, SITE_Z))
    points = np.array([[east, north, SITE_Z], [float("nan"), north, SITE_Z]])
    with pytest.raises(PlacementError, match="1 of 2 vertices do not convert"):
        to_local_enu_from_projected(points, frame)


# --------------------------------------- (6) what is localised, what is not

@pytest.mark.parametrize("crs", [
    "EPSG:32702",                                     # UTM, southern
    "EPSG:32602",                                     # UTM, northern
    "EPSG:32653",                                     # the NA168 zone
    "+proj=utm +zone=2 +south +datum=WGS84 +units=m +no_defs",
    TMERC_ON_SITE,
    "EPSG:26910",                                     # NAD83 / UTM 10N
    "EPSG:3031",                             # Antarctic polar stereographic
])
def test_a_metric_easting_northing_crs_is_supported(crs):
    assert check_projected_crs(crs)


@pytest.mark.parametrize("crs, why", [
    ("EPSG:4326", "geographic CRS"),
    ("EPSG:4979", "geographic CRS"),
    ("EPSG:4978", "geocentric CRS but the export is not marked geocentric"),
    ("EPSG:32702+3855", "compound CRS"),
    ("EPSG:3855", "not a projected CRS"),
    ("EPSG:2227", "US survey foot"),                  # California zone 3, ftUS
    ("EPSG:2193", "lists its axes as Northing"),      # NZTM2000: N, E
    ("EPSG:32661", "lists its axes as Northing"),     # UPS North: N, E
    ("EPSG:2053", "lists its axes as Westing"),       # south-oriented
    ("+proj=tmerc +lon_0=-169 +datum=WGS84 +units=us-ft", "US survey foot"),
    ("not a crs at all", "cannot be read by PROJ"),
])
def test_what_cannot_be_read_from_the_crs_is_refused(crs, why):
    """Metres and easting-then-northing are READ from the CRS. A CRS that
    says anything else is refused with what it does say; nothing is
    assumed and nothing is converted on a guess."""
    with pytest.raises(PlacementError, match=why):
        check_projected_crs(crs)


@pytest.mark.parametrize("epsg, why", [
    ("4326", "geographic CRS"),
    ("2227", "not metres"),
    ("2193", "Refusing rather than guessing which column is which"),
])
def test_an_unsupported_crs_stops_the_plan_before_the_mesh_is_read(
        tmp_path, epsg, why):
    """Through plan_placement, off a sidecar - and BEFORE the vertices are
    parsed: the OBJ here has none, which would be a different error."""
    (tmp_path / "m.obj").write_text("# no vertices\n", encoding="utf-8")
    (tmp_path / "m.obj.rsInfo").write_text(
        projected_sidecar("EPSG:" + epsg), encoding="utf-8")
    with pytest.raises(PlacementError, match=why):
        plan_placement([tmp_path / "m.obj"], apply_geoid=False)


def test_a_polar_stereographic_grid_is_localised_exactly(tmp_path,
                                                         monkeypatch):
    """Not UTM, and nowhere near axis-aligned: at 169 W on the Antarctic
    grid, grid north is 169 deg from true north. The route is the same and
    as exact; only the size of the turn differs."""
    stub_geoid(monkeypatch)
    lon, lat = SITE_LON, -75.0
    east, north = site_grid("EPSG:3031", lon, lat)
    verts = cross(east, north, SITE_Z)
    obj = write_obj(tmp_path, "m", verts,
                    sidecar=projected_sidecar("EPSG:3031"))
    plan, localised = plan_placement([obj])

    assert plan["lon"] == pytest.approx(lon, abs=1e-7)
    assert plan["lat"] == pytest.approx(lat, abs=1e-7)
    assert np.abs(localised[0][1] - reference_enu(
        verts, (east, north, SITE_Z), "EPSG:3031")).max() < 1e-6
    turn, gamma_deg, _k = grid_turn("EPSG:3031", lon, lat)
    assert gamma_deg == pytest.approx(169.047, abs=1e-3)
    assert plan["grid_convergence_deg"] == pytest.approx(gamma_deg, abs=1e-5)
    assert np.abs(np.array(plan["enu_rotation"]) - turn).max() < 1e-7
    # 50 m along grid east is mostly WEST here
    assert localised[0][1][1][0] < -49.0
