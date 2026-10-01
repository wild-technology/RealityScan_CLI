"""Geocentric (ECEF) mesh exports - exportCoordinateSystemType="3".

Traced to NA168/H2077 (2026-09-23). Its OBJ vertices are ECEF while the
sidecar's globalCoordinateSystemName says ``epsg:32653 - WGS 84 / UTM zone
53N``, because that names the PROJECT's CRS, not the export frame. Reading
the vertices as easting/northing/height anchored the asset at lon 87.117
lat 30.976 at +832 km - over Tibet, in low orbit - for a dive that sits at
132.8E 7.5N, depth -1497 m.

The label cannot be trusted even when it is present: NA165/H2063 shipped
c00 labelled epsg:32653, a 53N zone left over from the previous campaign,
alongside c22 labelled epsg:32702, and BOTH were ECEF. Keying on the
export type is what makes a wrong label harmless.

The geocentric localisation is a ROTATION, so these also pin that ``vn``
normals rotate with the geometry - a rotated mesh carrying unrotated
normals is lit from the wrong direction everywhere. (The projected route
was a translation until 2026-10-01 and is a rotation too since BUGS.md B28;
its tests are in test_cesium_projected_enu.py, including the one that puts
the same geometry through both routes.)
"""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

np = pytest.importorskip("numpy")

from modules.cesium_placement import (  # noqa: E402
    PlacementError, ecef_enu_rotation, parse_rsinfo, plan_placement,
    rewrite_obj_local, to_local_enu_from_ecef)

# H2077's real sidecar shape, trimmed. Type 3 with a PROJECTED label.
GEOCENTRIC = """<Model globalCoordinateSystem="+proj=utm +zone=53 +datum=WGS84 +units=m +no_defs"
   globalCoordinateSystemName="epsg:32653 - WGS 84 / UTM zone 53N"
   exportCoordinateSystemType="3"
   transformToModel="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1">
  <globalCoordinateSystemWkt>PROJCS["WGS_1984_UTM_Zone_53N"]</globalCoordinateSystemWkt>
  <Header magic="5786959" version="2"/>
</Model>
"""

PROJECTED = GEOCENTRIC.replace('exportCoordinateSystemType="3"',
                               'exportCoordinateSystemType="0"')

# H2077's own first vertex, and the site it resolves to. The GEODETIC
# latitude is 0.05 deg north of the geocentric one (7.5025); using the
# geocentric value as if it were geodetic is a ~5.5 km error, so the two
# are kept apart deliberately.
H2077_VERTEX = (-4295945.677965235, 4638341.647493453, 832605.0386298783)
H2077_LON, H2077_LAT = 132.805281, 7.552488
H2077_ELL_H = -1047.816


def _sidecar(tmp_path, name, body):
    p = tmp_path / (name + ".obj.rsInfo")
    p.write_text(body, encoding="utf-8")
    return p


def _obj(tmp_path, name, verts, normals=()):
    p = tmp_path / (name + ".obj")
    lines = ["# test"]
    lines += ["v %.6f %.6f %.6f" % v for v in verts]
    lines += ["vn %.6f %.6f %.6f" % n for n in normals]
    lines.append("f 1 1 1")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


# ------------------------------------------------------------- the type flag

def test_type_three_is_geocentric(tmp_path):
    info = parse_rsinfo(_sidecar(tmp_path, "a", GEOCENTRIC))
    assert info.is_geocentric is True
    assert info.vertex_crs == "EPSG:4978"


def test_other_types_keep_the_declared_crs(tmp_path):
    info = parse_rsinfo(_sidecar(tmp_path, "b", PROJECTED))
    assert info.is_geocentric is False
    assert info.vertex_crs == "EPSG:32653"


def test_a_wrong_projected_label_does_not_change_the_reading(tmp_path):
    """H2063 c00 carried a 53N label for a 2S site; still ECEF."""
    body = GEOCENTRIC.replace("32653", "32702").replace("zone 53N", "zone 2S")
    info = parse_rsinfo(_sidecar(tmp_path, "c", body))
    assert info.is_geocentric is True
    assert info.vertex_crs == "EPSG:4978"


# ------------------------------------------------------------- the rotation

def test_enu_rotation_is_orthonormal_and_right_handed():
    rot = ecef_enu_rotation(132.805, 7.503)
    assert np.allclose(rot @ rot.T, np.eye(3), atol=1e-12)
    assert np.isclose(np.linalg.det(rot), 1.0, atol=1e-12)


def test_up_points_away_from_the_earth_centre():
    lon, lat = 132.805, 7.503
    rot = ecef_enu_rotation(lon, lat)
    radial = np.array([
        math.cos(math.radians(lat)) * math.cos(math.radians(lon)),
        math.cos(math.radians(lat)) * math.sin(math.radians(lon)),
        math.sin(math.radians(lat))])
    assert np.allclose(rot[2], radial, atol=1e-12)     # Up row == radial
    assert np.isclose(rot[0] @ radial, 0.0, atol=1e-12)  # East perpendicular
    assert np.isclose(rot[1] @ radial, 0.0, atol=1e-12)  # North perpendicular


def test_anchor_maps_to_the_origin():
    anchor = np.array(H2077_VERTEX)
    local, _rot = to_local_enu_from_ecef(
        np.array([H2077_VERTEX]), anchor, H2077_LON, H2077_LAT)
    assert np.allclose(local[0], [0.0, 0.0, 0.0], atol=1e-6)


def test_a_purely_vertical_offset_lands_on_up():
    """A point 10 m further from the Earth's centre is 10 m Up, 0 E, 0 N."""
    anchor = np.array(H2077_VERTEX)
    radial = anchor / np.linalg.norm(anchor)
    local, _rot = to_local_enu_from_ecef(
        np.array([anchor + radial * 10.0]), anchor, H2077_LON, H2077_LAT)
    east, north, up = local[0]
    assert abs(up - 10.0) < 0.05
    assert abs(east) < 0.05 and abs(north) < 0.05


def test_rotation_preserves_distances():
    anchor = np.array(H2077_VERTEX)
    pts = anchor + np.array([[3.0, -4.0, 12.0], [0.0, 0.0, 0.0]])
    local, _rot = to_local_enu_from_ecef(pts, anchor, H2077_LON, H2077_LAT)
    assert np.isclose(np.linalg.norm(local[0] - local[1]), 13.0, atol=1e-6)


# ------------------------------------------------------------------ normals

def test_normals_rotate_with_the_geometry(tmp_path):
    rot = ecef_enu_rotation(H2077_LON, H2077_LAT)
    src = _obj(tmp_path, "n", [(1.0, 2.0, 3.0)], normals=[(1.0, 0.0, 0.0)])
    dst = tmp_path / "out.obj"
    rewrite_obj_local(src, dst, np.array([[0.0, 0.0, 0.0]]),
                      normal_rotation=rot)
    line = [l for l in dst.read_text().splitlines() if l.startswith("vn ")][0]
    got = np.array([float(x) for x in line.split()[1:]])
    assert np.allclose(got, rot @ np.array([1.0, 0.0, 0.0]), atol=1e-6)
    assert np.isclose(np.linalg.norm(got), 1.0, atol=1e-6)


def test_normals_untouched_without_a_rotation(tmp_path):
    """No rotation given, none applied: the ``vn`` lines pass through as
    they are. (Until B28 this was what the projected route did. It now
    hands over its own grid -> ENU rotation; this pins only that
    rewrite_obj_local invents none.)"""
    src = _obj(tmp_path, "p", [(1.0, 2.0, 3.0)], normals=[(0.0, 0.0, 1.0)])
    dst = tmp_path / "out.obj"
    rewrite_obj_local(src, dst, np.array([[0.0, 0.0, 0.0]]))
    line = [l for l in dst.read_text().splitlines() if l.startswith("vn ")][0]
    assert line.split()[1:] == ["0.000000", "0.000000", "1.000000"]


# ------------------------------------------------------------ plan_placement

def _geocentric_export(tmp_path, name="m"):
    anchor = np.array(H2077_VERTEX)
    radial = anchor / np.linalg.norm(anchor)
    pts = [tuple(anchor), tuple(anchor + radial * 4.0)]
    _sidecar(tmp_path, name, GEOCENTRIC)
    return _obj(tmp_path, name, pts)


def test_geocentric_plan_lands_at_the_real_site(tmp_path):
    pytest.importorskip("pyproj")
    obj = _geocentric_export(tmp_path)
    plan, _localised = plan_placement([obj], apply_geoid=False)
    assert plan["geocentric"] is True
    assert plan["crs"] == "EPSG:4978"
    # Tibet was lon 87.1 lat 31.0; the dive is 132.8E 7.55N. 1e-4 deg is
    # ~11 m, so this pins the real site rather than merely the hemisphere.
    assert abs(plan["lon"] - H2077_LON) < 1e-4
    assert abs(plan["lat"] - H2077_LAT) < 1e-4
    assert abs(plan["ecef_height_m"] - H2077_ELL_H) < 5.0


def test_geocentric_plan_applies_the_geoid(tmp_path, monkeypatch):
    """RealityScan's ECEF height is the flight log's -depth (measured on
    NA165/H2060, 2026-09-28), so the geocentric path adds N exactly as the
    projected path does. The grid is stubbed: the unit test checks the
    arithmetic and the plan fields, not PROJ."""
    pytest.importorskip("pyproj")
    from modules import cesium_placement as cp
    monkeypatch.setattr(cp, "geoid_separation", lambda lon, lat, model="EGM2008": 65.85)
    obj = _geocentric_export(tmp_path)
    plan, _localised = plan_placement([obj])
    assert plan["geoid_n_m"] == 65.85
    assert plan["geoid_model"] == "EGM2008"
    assert plan["height_ellipsoidal_m"] == pytest.approx(plan["ecef_height_m"] + 65.85)
    assert plan["depth_msl_m"] == plan["ecef_height_m"]


def test_geocentric_no_geoid_keeps_the_raw_ecef_height(tmp_path):
    pytest.importorskip("pyproj")
    obj = _geocentric_export(tmp_path)
    plan, _localised = plan_placement([obj], apply_geoid=False)
    assert plan["geoid_n_m"] == 0.0
    assert plan["geoid_model"] == "NONE"
    assert plan["height_ellipsoidal_m"] == plan["ecef_height_m"]


def test_geocentric_geoid_shifts_only_the_anchor(tmp_path, monkeypatch):
    """The localised (ENU) mesh is identical with or without the geoid; only
    options.position moves, by exactly N."""
    pytest.importorskip("pyproj")
    from modules import cesium_placement as cp
    monkeypatch.setattr(cp, "geoid_separation", lambda lon, lat, model="EGM2008": 25.2)
    obj = _geocentric_export(tmp_path)
    with_n, loc_n = plan_placement([obj])
    without, loc_0 = plan_placement([obj], apply_geoid=False)
    assert np.allclose(loc_n[0][1], loc_0[0][1])
    assert with_n["height_ellipsoidal_m"] - without["height_ellipsoidal_m"] == pytest.approx(25.2)
    assert (with_n["lon"], with_n["lat"]) == (without["lon"], without["lat"])


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
def test_geocentric_non_finite_geoid_never_becomes_a_finite_placement(
        tmp_path, monkeypatch, bad):
    """BUGS.md B26, the geocentric half (the projected twin is in
    test_cesium_placement.py). geoid_separation returns inf when the grid
    is missing, PROJ network is on and the CDN is unreachable, and this
    branch checks only the ECEF conversion. A refusal - the fix - passes;
    until then the bad value must at least stay visible in the plan rather
    than turn into a height that looks like a placement."""
    pytest.importorskip("pyproj")
    from modules import cesium_placement as cp
    monkeypatch.setattr(cp, "geoid_separation", lambda lon, lat, model="EGM2008": bad)
    obj = _geocentric_export(tmp_path)
    try:
        plan, _localised = plan_placement([obj])
    except PlacementError:
        return
    assert not math.isfinite(plan["height_ellipsoidal_m"])
    assert not math.isfinite(plan["geoid_n_m"])


def test_mixing_geocentric_and_projected_is_refused(tmp_path):
    pytest.importorskip("pyproj")
    a = _geocentric_export(tmp_path, "one")
    _sidecar(tmp_path, "two", PROJECTED)
    b = _obj(tmp_path, "two", [(257400.0, 835800.0, -1050.0)])
    with pytest.raises(PlacementError, match="mix geocentric and projected"):
        plan_placement([a, b])
