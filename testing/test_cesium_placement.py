"""Cesium ion placement: CRS, frame resolution and the vertical datum.

Every case here traces to something found on real data (2026-08-31):

- the NA168 H2080 OBJ sits in a local frame ~350 km from its site, so the
  ``transformToModel`` reading is load-bearing and must be DERIVED, not
  assumed - the matrix has no single obvious reading;
- the pipeline's Z is a depth below the SEA SURFACE while ion reads every
  height as ellipsoidal, and PROJ silently applies a ZERO geoid correction
  when the grid is missing;
- the three assets already on the ion account sit at the sea surface, which
  is what happens when nobody checks placement after upload.

Hermetic: no network, no RealityScan, no multi-GB fixtures. The geoid tests
exercise the guard rather than the grid, so they pass with or without
cdn.proj.org reachable.

Added 2026-10-01: ``plan_placement`` on a PROJECTED export with the grid
stubbed to a known N. Mutation testing that morning showed the projected
branch - the one every nav-placed product takes - had no geoid test at all:
a sign flip of N confined to it, leaving N out, and adding it twice each
passed this file and test_cesium_geocentric.py.

Changed the same day (BUGS.md B28): the projected branch no longer
localises by subtracting the anchor. A UTM grid is turned from East / North
by the meridian convergence - 0.48 deg at NA165/H2060 - so the mesh goes to
true East-North-Up, as the geocentric branch's always did. Three tests here
pinned the translation and now pin the true frame instead
(``projected_local`` below; ``test_cesium_projected_enu.py`` holds the tests
of the frame itself). The geoid invariants are what they were.
"""
import logging
import math
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

np = pytest.importorskip("numpy")

from modules.cesium_placement import (  # noqa: E402
    PlacementError, apply_interpretation, find_rsinfo, geoid_separation,
    msl_to_ellipsoidal, nav_envelope_from_flight_log, parse_rsinfo,
    plan_placement, projected_frame, read_obj_vertices, resolve_to_global,
    rewrite_obj_local, to_local_enu_from_projected)

# The real NA168 H2080 sidecar matrix, verbatim.
NA168_MATRIX = ("0 0 1 348355.8364815 1 0 0 396321.994618801 "
                "0 1 0 -587.41083970014 0 0 0 1")

RSINFO_ELEMENT = """<Model globalCoordinateSystem="+proj=utm +zone=53 +datum=WGS84 +units=m +no_defs"
   globalCoordinateSystemName="epsg:32653 - WGS 84 / UTM zone 53N" exportCoordinateSystemType="2">
  <globalCoordinateSystemWkt>PROJCS["WGS_1984_UTM_Zone_53N"]</globalCoordinateSystemWkt>
  <transformToModel>%s</transformToModel>
  <Header magic="5786959" version="1"/>
</Model>
<ModelExport exportBinary="1"/>
""" % NA168_MATRIX

RSINFO_ATTRIBUTE = """<Model globalCoordinateSystem="+proj=utm +zone=4 +datum=WGS84 +units=m +no_defs"
   globalCoordinateSystemName="epsg:32604 - WGS 84 / UTM zone 4N" exportCoordinateSystemType="1"
   transformToModel="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1">
  <Header magic="5786959" version="1"/>
</Model>
"""


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# sidecar parsing
# --------------------------------------------------------------------------

def test_parses_matrix_from_child_element(tmp_path):
    info = parse_rsinfo(write(tmp_path, "m.obj.rsInfo", RSINFO_ELEMENT))
    assert info.epsg == "EPSG:32653"
    assert info.crs == "EPSG:32653"
    assert info.export_cs_type == "2"
    assert len(info.transform) == 16
    assert info.transform[3] == pytest.approx(348355.8364815)


def test_parses_matrix_from_attribute(tmp_path):
    # The LAS sidecar carries the matrix as an attribute, not a child.
    info = parse_rsinfo(write(tmp_path, "m.las.rcInfo", RSINFO_ATTRIBUTE))
    assert info.epsg == "EPSG:32604"
    assert info.transform == tuple(np.eye(4).reshape(-1))


def test_sidecar_without_model_tag_is_an_error(tmp_path):
    path = write(tmp_path, "m.obj.rsInfo", "<ModelExport exportBinary='1'/>")
    with pytest.raises(PlacementError, match="no <Model> tag"):
        parse_rsinfo(path)


def test_malformed_matrix_is_refused_not_guessed(tmp_path):
    bad = RSINFO_ELEMENT.replace(NA168_MATRIX, "1 0 0 0 0 1 0 0")
    with pytest.raises(PlacementError, match="expected"):
        parse_rsinfo(write(tmp_path, "m.obj.rsInfo", bad))


def test_sidecar_without_crs_names_the_remedy(tmp_path):
    path = write(tmp_path, "m.obj.rsInfo", "<Model><Header version='1'/></Model>")
    info = parse_rsinfo(path)
    with pytest.raises(PlacementError, match="MvsExportIsGeoreferenced"):
        _ = info.crs


def test_find_rsinfo_matches_case_insensitively(tmp_path):
    obj = write(tmp_path, "m.obj", "v 0 0 0\n")
    write(tmp_path, "m.obj.rsinfo", RSINFO_ELEMENT)
    assert find_rsinfo(obj) is not None


def test_find_rsinfo_returns_none_when_absent(tmp_path):
    assert find_rsinfo(write(tmp_path, "m.obj", "v 0 0 0\n")) is None


# --------------------------------------------------------------------------
# frame resolution - the NA168 case
# --------------------------------------------------------------------------

def na168_vertices(n=64):
    """Model-frame points that map to the real site under the true reading."""
    rng = np.random.default_rng(0)
    # True global site: E ~348355, N ~396320, Z ~ -585.
    east = 348355.0 + rng.uniform(-6, 6, n)
    north = 396320.0 + rng.uniform(-6, 6, n)
    depth = -585.0 + rng.uniform(-15, 15, n)
    # Invert the established mapping E=x+396321.994618801,
    # N=y-587.41083970014, Z=z+348355.8364815.
    return np.c_[east - 396321.994618801,
                 north + 587.41083970014,
                 depth - 348355.8364815]


def test_resolves_the_real_na168_frame(tmp_path):
    info = parse_rsinfo(write(tmp_path, "m.obj.rsInfo", RSINFO_ELEMENT))
    vertices = na168_vertices()
    out, interp = resolve_to_global(vertices, info)
    assert interp is not None
    assert out[:, 0].min() > 348_000 and out[:, 0].max() < 349_000
    assert out[:, 1].min() > 396_000 and out[:, 1].max() < 397_000
    assert -620 < out[:, 2].min() and out[:, 2].max() < -550


def test_identity_transform_is_a_passthrough(tmp_path):
    info = parse_rsinfo(write(tmp_path, "m.las.rcInfo", RSINFO_ATTRIBUTE))
    vertices = np.array([[600000.0, 2345000.0, -1200.0]])
    out, interp = resolve_to_global(vertices, info)
    assert interp is None
    assert np.allclose(out, vertices)


def test_geometry_outside_the_declared_crs_is_refused(tmp_path):
    """A mesh that no reading can place is an error, never a best guess."""
    info = parse_rsinfo(write(tmp_path, "m.obj.rsInfo", RSINFO_ELEMENT))
    absurd = np.full((16, 3), 5.0e9)
    with pytest.raises(PlacementError, match="no reading of transformToModel"):
        resolve_to_global(absurd, info)


def test_nav_envelope_can_veto_a_crs_valid_reading(tmp_path):
    """The CRS area of use is coarse; the dive's own nav is the tighter
    oracle and must be able to reject."""
    info = parse_rsinfo(write(tmp_path, "m.obj.rsInfo", RSINFO_ELEMENT))
    vertices = na168_vertices()
    wrong = {"east": (500000.0, 500100.0),
             "north": (100000.0, 100100.0),
             "alt": (-10.0, 0.0)}
    with pytest.raises(PlacementError):
        resolve_to_global(vertices, info, nav_envelope=wrong)


def test_reflections_are_rejected_before_scoring(tmp_path):
    """The E/N swap the CRS bounds cannot see.

    On this site easting (~348 355) and northing (~396 320) are each
    plausible as the other, so perm(1,2,0) and perm(2,1,0) both land every
    vertex inside UTM 53N. They differ by one axis swap, which is a
    reflection - determinant -1 - so only the proper one survives.
    """
    from modules.cesium_placement import Interpretation, preserves_orientation
    info = parse_rsinfo(write(tmp_path, "m.obj.rsInfo", RSINFO_ELEMENT))
    proper = Interpretation("row-major", "Mv", (1, 2, 0))
    mirrored = Interpretation("row-major", "Mv", (2, 1, 0))
    assert preserves_orientation(info.transform, proper)
    assert not preserves_orientation(info.transform, mirrored)


def test_resolution_does_not_need_a_flight_log(tmp_path):
    """Nav is a second opinion, not a prerequisite - proven on the real
    NA168 matrix, which resolves identically with and without it."""
    info = parse_rsinfo(write(tmp_path, "m.obj.rsInfo", RSINFO_ELEMENT))
    vertices = na168_vertices()
    without, interp_a = resolve_to_global(vertices, info)
    envelope = {"east": (348265.0, 349295.3),
                "north": (396250.0, 396914.2),
                "alt": (-1030.92, -532.16)}
    with_nav, interp_b = resolve_to_global(vertices, info,
                                           nav_envelope=envelope)
    assert str(interp_a) == str(interp_b)
    assert np.allclose(without, with_nav)


def test_apply_interpretation_is_pure(tmp_path):
    from modules.cesium_placement import Interpretation
    info = parse_rsinfo(write(tmp_path, "m.obj.rsInfo", RSINFO_ELEMENT))
    vertices = na168_vertices(8)
    before = vertices.copy()
    apply_interpretation(vertices, info.transform,
                         Interpretation("row-major", "Mv", (1, 2, 0)))
    assert np.array_equal(vertices, before)


# --------------------------------------------------------------------------
# vertical datum
# --------------------------------------------------------------------------

def test_unknown_geoid_model_is_refused():
    with pytest.raises(PlacementError, match="unknown geoid model"):
        geoid_separation(0.0, 0.0, model="EGM2525")


def test_geoid_is_either_applied_or_raises_never_silently_zero():
    """The failure this guards: PROJ picks a 'ballpark' vertical operation
    when the grid is missing and returns Z UNCHANGED, reporting success."""
    try:
        separation = geoid_separation(-157.08, 18.81)
    except PlacementError as exc:
        assert "geoid" in str(exc).lower()
        assert "us_nga_egm08_25.tif" in str(exc)
        return
    # Grid present: a real undulation, and near Hawaii it is strongly
    # positive - a 0.0 here would be the silent no-op leaking through.
    assert separation != 0.0
    assert 0.0 < separation < 30.0


def test_depth_to_ellipsoidal_applies_h_equals_H_plus_N():
    try:
        height, separation = msl_to_ellipsoidal(-1200.0, -157.08, 18.81)
    except PlacementError:
        pytest.skip("geoid grid unavailable offline")
    assert height == pytest.approx(-1200.0 + separation)
    # A depth must stay below the ellipsoid at these magnitudes.
    assert height < 0


# --------------------------------------------------------------------------
# vertical datum on a PROJECTED export - the branch a nav-placed product takes
# --------------------------------------------------------------------------

# What georef_v2.py writes beside a nav-placed NA165/H2060 product: the
# project CRS, exportCoordinateSystemType 0 and NO transformToModel. The
# vertices are UTM easting / northing with Z = -depth below the sea surface.
RSINFO_PROJECTED = (
    '<Model globalCoordinateSystem="+proj=utm +zone=2 +south +datum=WGS84 '
    '+units=m +no_defs" '
    'globalCoordinateSystemName="epsg:32702 - WGS 84 / UTM zone 2S" '
    'exportCoordinateSystemType="0"/>\n')

# Five vertices at the H2060 site. Their bounding-box midpoint - the anchor -
# is exactly E 710830, N 8428136, Z -650, which is lon -169.046249,
# lat -14.210270. Every number is exactly representable in binary, so the
# assertions below use == rather than a tolerance half an N could hide in.
PROJECTED_VERTS = [(710825.0, 8428130.0, -652.0),
                   (710835.0, 8428142.0, -648.0),
                   (710830.0, 8428136.0, -650.0),
                   (710825.0, 8428142.0, -649.0),
                   (710835.0, 8428130.0, -651.0)]
PROJECTED_ANCHOR = (710830.0, 8428136.0, -650.0)
# What the mesh was before B28: the vertices minus the anchor. Kept to show
# the localised mesh is NOT this any more, and by how much.
PROJECTED_TRANSLATED = np.array(PROJECTED_VERTS) - np.array(PROJECTED_ANCHOR)
PROJECTED_LON, PROJECTED_LAT = -169.046249, -14.210270
STUB_N = 25.25


def true_enu(verts, anchor, crs):
    """(E, N, Z) rows in TRUE East-North-Up about an (E, N, Z) anchor.

    Derived with PROJ and three lines of trigonometry, not with the module:
    grid -> lon / lat, the Z as the height (so no geoid is in it), -> ECEF,
    and the East / North / Up directions at the anchor."""
    from pyproj import Transformer
    to_geo = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    to_ecef = Transformer.from_crs("EPSG:4979", "EPSG:4978", always_xy=True)
    verts = np.asarray(verts, dtype="float64")
    lon, lat = to_geo.transform(verts[:, 0], verts[:, 1])
    ecef = np.c_[to_ecef.transform(lon, lat, verts[:, 2])]
    lon0, lat0 = to_geo.transform(anchor[0], anchor[1])
    origin = np.array(to_ecef.transform(lon0, lat0, anchor[2]))
    lam, phi = math.radians(lon0), math.radians(lat0)
    basis = np.array([
        [-math.sin(lam), math.cos(lam), 0.0],
        [-math.sin(phi) * math.cos(lam), -math.sin(phi) * math.sin(lam),
         math.cos(phi)],
        [math.cos(phi) * math.cos(lam), math.cos(phi) * math.sin(lam),
         math.sin(phi)]])
    return (ecef - origin) @ basis.T


def projected_local():
    """Where PROJECTED_VERTS belong in the frame ion is given. Grid north
    is 0.48 deg from true north at this anchor, so the corners sit up to
    5.4 cm from where the old translation put them."""
    return true_enu(PROJECTED_VERTS, PROJECTED_ANCHOR, "EPSG:32702")


def projected_export(tmp_path, name="m"):
    write(tmp_path, name + ".obj.rsInfo", RSINFO_PROJECTED)
    body = "".join("v %.3f %.3f %.3f\n" % v for v in PROJECTED_VERTS)
    return write(tmp_path, name + ".obj", body + "f 1 2 3\n")


def stub_geoid(monkeypatch, value):
    """Stand a known N in for the grid, and record how it was asked for.

    The arithmetic is what is under test - the sign, and that N is added
    once - so the grid is not needed and the test is the same on a machine
    without it."""
    from modules import cesium_placement as cp
    calls = []

    def fake(lon, lat, model="EGM2008"):
        calls.append((lon, lat, model))
        return value

    monkeypatch.setattr(cp, "geoid_separation", fake)
    return calls


@pytest.mark.parametrize("undulation, height", [
    (STUB_N, -624.75),      # NA165/H2060: the geoid is above the ellipsoid
    (-27.0, -677.0),        # Gulf of Mexico: it is below, and N is negative
])
def test_projected_plan_adds_the_geoid_exactly_once(tmp_path, monkeypatch,
                                                    caplog, undulation,
                                                    height):
    """h = H + N with H = Z = -depth: -650 + 25.25 = -624.75. A flipped
    sign gives -675.25, a forgotten N -650, a doubled one -599.5.

    And with N = -27: -677. While only a positive N was stubbed,
    ``depth + abs(N)`` passed (review mutant R6, 2026-10-01); it gives
    -623 here."""
    pytest.importorskip("pyproj")
    calls = stub_geoid(monkeypatch, undulation)
    with caplog.at_level(logging.WARNING, logger="modules.cesium_placement"):
        plan, _localised = plan_placement([projected_export(tmp_path)])

    assert plan["crs"] == "EPSG:32702"
    assert not plan.get("geocentric")
    assert plan["depth_msl_m"] == -650.0
    assert plan["geoid_n_m"] == undulation
    assert plan["geoid_model"] == "EGM2008"
    assert plan["height_ellipsoidal_m"] == -650.0 + undulation == height

    # N was looked up at the anchor - the real site, not merely the right
    # hemisphere (1e-4 deg is ~11 m) - and with the model the plan reports.
    assert calls
    for lon, lat, model in calls:
        assert (lon, lat) == (plan["lon"], plan["lat"])
        assert model == "EGM2008"
    assert abs(plan["lon"] - PROJECTED_LON) < 1e-4
    assert abs(plan["lat"] - PROJECTED_LAT) < 1e-4
    assert "GEOID CORRECTION DISABLED" not in caplog.text


def test_projected_no_geoid_keeps_the_depth_and_warns(tmp_path, monkeypatch,
                                                      caplog):
    """--no-geoid: the height is the raw Z, the plan says model NONE and
    N 0, the grid is never consulted, and the operator is told the asset
    will be wrong by the undulation."""
    pytest.importorskip("pyproj")
    from modules import cesium_placement as cp

    def consulted(*_args, **_kwargs):
        raise AssertionError("the geoid was consulted with apply_geoid=False")

    monkeypatch.setattr(cp, "geoid_separation", consulted)
    with caplog.at_level(logging.WARNING, logger="modules.cesium_placement"):
        plan, _localised = plan_placement([projected_export(tmp_path)],
                                          apply_geoid=False)

    assert plan["height_ellipsoidal_m"] == -650.0
    assert plan["depth_msl_m"] == -650.0
    assert plan["geoid_n_m"] == 0.0
    assert plan["geoid_model"] == "NONE"
    warned = [r.getMessage() for r in caplog.records
              if r.levelno >= logging.WARNING]
    assert any("GEOID CORRECTION DISABLED" in message for message in warned)


def test_projected_geoid_moves_the_anchor_and_never_the_mesh(tmp_path,
                                                             monkeypatch):
    """The localised mesh is the same with and without the geoid, and is
    the vertices in true East-North-Up about the anchor - no N in it. Only
    the height in options.position moves, by exactly N. Baking N into the
    mesh as well would place every vertex 25 m off while the plan still
    read right.

    Changed for B28: this asserted the mesh was the vertices MINUS the
    anchor, to 1e-9, with extents [10, 12, 4] - the translation that left
    every projected upload turned by the grid convergence. The frame is now
    the true one; that the geoid stays out of it is asserted more strictly
    than before (the two meshes are equal, not merely close)."""
    pytest.importorskip("pyproj")
    stub_geoid(monkeypatch, STUB_N)
    obj = projected_export(tmp_path)
    with_n, loc_n = plan_placement([obj])
    without, loc_0 = plan_placement([obj], apply_geoid=False)

    expected = projected_local()
    assert np.array_equal(loc_n[0][1], loc_0[0][1])
    assert np.allclose(loc_n[0][1], expected, atol=1e-6)
    # Up is the vertices' own Z about the anchor: no undulation in it
    assert loc_n[0][1][:, 2].min() == pytest.approx(-2.0, abs=1e-4)
    assert loc_n[0][1][:, 2].max() == pytest.approx(2.0, abs=1e-4)
    # ... and it is not the translation: the corners are 5.4 cm away
    moved = np.abs(loc_n[0][1] - PROJECTED_TRANSLATED).max()
    assert 0.04 < moved < 0.06

    assert (with_n["height_ellipsoidal_m"]
            - without["height_ellipsoidal_m"]) == STUB_N
    assert (with_n["lon"], with_n["lat"]) == (without["lon"], without["lat"])
    assert (with_n["anchor_projected"] == without["anchor_projected"]
            == list(PROJECTED_ANCHOR))
    # East x North x Up of the mesh that is uploaded - what ion's tight box
    # reports and --verify compares - not the grid's [10, 12, 4]
    assert with_n["extent_m"] == without["extent_m"]
    assert with_n["extent_m"] == pytest.approx(
        list(expected.max(axis=0) - expected.min(axis=0)), abs=1e-6)
    assert with_n["extent_m"] == pytest.approx([10.097, 12.080, 4.0],
                                               abs=1e-3)


def test_ion_is_handed_n_in_the_position_and_nowhere_in_the_mesh(tmp_path,
                                                                 monkeypatch):
    """End to end as far as the wire: the staged OBJ - the file that is
    uploaded - holds true East-North-Up metres about the anchor, and the
    request body's position carries Z + N.

    Changed for B28: this asserted ``enu_rotation is None`` ("a
    translation, no rotation") and a staged mesh equal to the vertices
    minus the anchor - the defect, pinned."""
    pyproj = pytest.importorskip("pyproj")
    from publish_cesium import create_asset, stage
    stub_geoid(monkeypatch, STUB_N)
    export = tmp_path / "export"
    export.mkdir()
    obj = projected_export(export)
    plan, localised = plan_placement([obj])

    # the turn from grid axes to East-North-Up: about Up, by PROJ's own
    # meridian convergence at the anchor, and not nothing
    rotation = np.array(plan["enu_rotation"])
    assert np.allclose(rotation @ rotation.T, np.eye(3), atol=1e-12)
    assert np.allclose(rotation[2], [0.0, 0.0, 1.0], atol=1e-9)
    gamma = pyproj.Proj("EPSG:32702").get_factors(
        plan["lon"], plan["lat"]).meridian_convergence
    assert gamma == pytest.approx(-0.48, abs=0.005)
    assert rotation[0][1] == pytest.approx(math.sin(math.radians(gamma)),
                                           abs=1e-8)
    staged = stage(localised, tmp_path / "staging", [obj],
                   normal_rotation=plan.get("enu_rotation"))
    (staged_obj,) = [p for p in staged if p.suffix == ".obj"]
    assert np.allclose(read_obj_vertices(staged_obj), projected_local(),
                       atol=1e-6)
    assert not np.allclose(read_obj_vertices(staged_obj),
                           PROJECTED_TRANSLATED, atol=0.04)

    posted = {}

    class Session:
        def post(self, url, json=None, timeout=None):
            posted.update(json)
            return types.SimpleNamespace(status_code=200, json=lambda: {})

    create_asset(Session(), "probe", "", plan, "KTX2", "DRACO")
    assert posted["options"]["position"] == [plan["lon"], plan["lat"], -624.75]
    assert "inputCrs" not in posted["options"]


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
def test_a_non_finite_geoid_never_becomes_a_finite_placement(tmp_path,
                                                             monkeypatch, bad):
    """BUGS.md B26. With the grid missing, PROJ network on and the CDN
    unreachable, geoid_separation returns inf, and plan_placement checks
    the result on neither branch. This does NOT enshrine that: a refusal -
    the fix - passes, and until it lands the only demand is that the bad
    value stays visible in the plan instead of being laundered into a
    height that looks like a placement. Tighten to pytest.raises when the
    guard exists."""
    pytest.importorskip("pyproj")
    stub_geoid(monkeypatch, bad)
    try:
        plan, _localised = plan_placement([projected_export(tmp_path)])
    except PlacementError:
        return
    assert not math.isfinite(plan["height_ellipsoidal_m"])
    assert not math.isfinite(plan["geoid_n_m"])


class _FailedLookup:
    """A PROJ transformer whose vertical came back as ``value`` - what a
    failed grid lookup looks like from Python (it does not raise)."""

    def __init__(self, value):
        self.value = value

    def transform(self, lon, lat, z):
        return lon, lat, self.value


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_failed_grid_lookup_never_returns_a_finite_separation(monkeypatch,
                                                                bad):
    """No grid needed: the transformer itself is replaced. NaN is refused
    today and must stay refused; inf is not (B26), and here too a refusal
    passes while a finite number in its place would not."""
    pyproj = pytest.importorskip("pyproj")
    monkeypatch.setattr(pyproj.Transformer, "from_crs",
                        staticmethod(lambda *a, **k: _FailedLookup(bad)))
    try:
        value = geoid_separation(132.805, 7.5525)
    except PlacementError as exc:
        assert "undefined" in str(exc)
        return
    assert not math.isnan(bad), "the NaN guard in geoid_separation is gone"
    assert not math.isfinite(value)


# --------------------------------------------------------------------------
# local frame
# --------------------------------------------------------------------------

def test_the_projected_localisation_is_true_enu_not_a_translation():
    """Replaces ``test_to_local_enu_is_a_pure_translation``, which pinned
    the defect (BUGS.md B28): ``to_local_enu`` subtracted the anchor and
    called grid axes East / North. Same two NA168/H2080 points. The site is
    152 km west of the central meridian of zone 53N, where the grid is
    turned only 0.085 deg - so the old answer, [5, 5, 10], was 7 mm out
    here; at NA165/H2060 the same code was 0.48 deg out."""
    pyproj = pytest.importorskip("pyproj")
    points = np.array([[348360.0, 396325.0, -580.0],
                       [348350.0, 396315.0, -600.0]])
    anchor = (348355.0, 396320.0, -590.0)
    frame = projected_frame("EPSG:32653", anchor)
    local = to_local_enu_from_projected(points, frame)

    assert np.allclose(local, true_enu(points, anchor, "EPSG:32653"),
                       atol=1e-6)
    assert np.allclose(local[0], -local[1], atol=1e-5)
    assert local[0][2] == pytest.approx(10.0, abs=1e-4)      # Up is Z
    # turned by PROJ's own convergence at the anchor, clockwise-positive
    gamma = pyproj.Proj("EPSG:32653").get_factors(
        frame.lon, frame.lat).meridian_convergence
    assert gamma == pytest.approx(-0.0855, abs=1e-3)
    assert frame.convergence_deg == pytest.approx(gamma, abs=1e-6)
    bearing = math.degrees(math.atan2(local[0][0], local[0][1]))
    assert bearing == pytest.approx(45.0 + gamma, abs=1e-4)
    assert 0.005 < np.abs(local[0][:2] - [5.0, 5.0]).max() < 0.010
    # Metric: the two are as far apart as the straight line between them.
    to_geo = pyproj.Transformer.from_crs("EPSG:32653", "EPSG:4326",
                                         always_xy=True)
    to_ecef = pyproj.Transformer.from_crs("EPSG:4979", "EPSG:4978",
                                          always_xy=True)
    lon, lat = to_geo.transform(points[:, 0], points[:, 1])
    ecef = np.c_[to_ecef.transform(lon, lat, points[:, 2])]
    assert np.linalg.norm(local[0] - local[1]) == pytest.approx(
        np.linalg.norm(ecef[0] - ecef[1]), abs=1e-6)


# --------------------------------------------------------------------------
# OBJ IO
# --------------------------------------------------------------------------

OBJ = """# comment
mtllib m.mtl
v 1.0 2.0 3.0
vt 0.5 0.5
vn 0.0 0.0 1.0
usemtl mat
v 4.0 5.0 6.0
f 1/1/1 2/1/1 1/1/1
"""


def test_read_obj_vertices(tmp_path):
    vertices = read_obj_vertices(write(tmp_path, "m.obj", OBJ))
    assert vertices.shape == (2, 3)
    assert np.allclose(vertices[1], [4.0, 5.0, 6.0])


def test_empty_obj_is_an_error(tmp_path):
    with pytest.raises(PlacementError, match="no vertices"):
        read_obj_vertices(write(tmp_path, "m.obj", "# nothing\n"))


def test_rewrite_preserves_everything_but_vertices(tmp_path):
    src = write(tmp_path, "m.obj", OBJ)
    dst = tmp_path / "out" / "m.obj"
    written = rewrite_obj_local(src, dst, np.array([[0.0, 0.0, 0.0],
                                                    [3.0, 3.0, 3.0]]))
    assert written == 2
    lines = dst.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "# comment"
    assert lines[1] == "mtllib m.mtl"
    assert lines[2] == "v 0.000000 0.000000 0.000000"
    assert "vt 0.5 0.5" in lines
    assert "vn 0.0 0.0 1.0" in lines
    assert "usemtl mat" in lines
    assert lines[-1] == "f 1/1/1 2/1/1 1/1/1"


def test_rewrite_refuses_a_vertex_count_mismatch(tmp_path):
    src = write(tmp_path, "m.obj", OBJ)
    with pytest.raises(PlacementError, match="rewrote"):
        rewrite_obj_local(src, tmp_path / "o.obj", np.zeros((5, 3)))


# --------------------------------------------------------------------------
# flight-log envelope
# --------------------------------------------------------------------------

LOG = ("Name;X (East);Y (North);Alt;XA;YA;AA;Yaw;Pitch;Roll;YA;PA;RA\n"
       "a.png;349269.824087;396839.016718;-1021.554931;10;10;1;0;0;0;3;30;3\n"
       "b.png;348265.001521;396250.014859;-532.163472;10;10;1;0;0;0;3;30;3\n"
       "c.png;0.000000;0.000000;0.000000;10;10;1;0;0;0;3;30;3\n")


def test_nav_envelope_excludes_missing_nav_rows(tmp_path):
    envelope = nav_envelope_from_flight_log(write(tmp_path, "fl.txt", LOG))
    # The 0;0;0 row is the pipeline's missing-nav marker. Including it would
    # stretch the envelope to the origin and validate any reading at all.
    assert envelope["east"] == (348265.001521, 349269.824087)
    assert envelope["north"] == (396250.014859, 396839.016718)
    assert envelope["alt"] == (-1021.554931, -532.163472)


def test_nav_envelope_with_no_usable_rows_is_an_error(tmp_path):
    header = LOG.splitlines()[0] + "\n"
    with pytest.raises(PlacementError, match="no usable nav rows"):
        nav_envelope_from_flight_log(write(tmp_path, "fl.txt", header))


# --------------------------------------------------------------------------
# whole-vs-parts selection
# --------------------------------------------------------------------------

def make_objs(tmp_path, names):
    for name in names:
        write(tmp_path, name, "v 0 0 0\n")
    return tmp_path


def test_whole_wins_over_its_by_parts_twin(tmp_path):
    """Publishing both would submit the same geometry twice: NA168 H2080 has
    178,269 vertices whole against 180,002 across nine parts."""
    from publish_cesium import select_objs
    make_objs(tmp_path, ["m.obj", "m_0000000.obj", "m_0000001.obj"])
    assert [p.name for p in select_objs(tmp_path, "whole")] == ["m.obj"]


def test_split_mode_picks_the_parts(tmp_path):
    from publish_cesium import select_objs
    make_objs(tmp_path, ["m.obj", "m_0000000.obj", "m_0000001.obj"])
    assert [p.name for p in select_objs(tmp_path, "split")] == [
        "m_0000000.obj", "m_0000001.obj"]


def test_an_unrelated_component_is_not_dropped(tmp_path):
    """Only the losing side of an AMBIGUOUS group is dropped. An earlier
    filter excluded every unsuffixed OBJ and silently lost this one."""
    from publish_cesium import select_objs
    make_objs(tmp_path, ["a.obj", "b.obj", "b_0000000.obj"])
    assert [p.name for p in select_objs(tmp_path, "whole")] == [
        "a.obj", "b.obj"]
    assert [p.name for p in select_objs(tmp_path, "split")] == [
        "a.obj", "b_0000000.obj"]


def test_parts_only_export_needs_no_choice(tmp_path):
    from publish_cesium import select_objs
    make_objs(tmp_path, ["m_0000000.obj", "m_0000001.obj"])
    assert len(select_objs(tmp_path, "whole")) == 2


def test_a_directory_with_no_obj_is_an_error(tmp_path):
    from publish_cesium import select_objs
    with pytest.raises(SystemExit, match="no .obj files"):
        select_objs(tmp_path, "whole")


# --------------------------------------------------------------------------
# the contract with the EXPORT stage
# --------------------------------------------------------------------------

EXPORT_PRESETS = ["ModelExportParamsOBJ_NiraParts",
                  "ModelExportParamsFBX_Parts",
                  "ModelExportParamsPLY_DensePoints"]


def preset(name):
    import xml.etree.ElementTree as ET
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "modules", "realityscan_interface", "RS_CLI", "Metadata", name + ".xml")
    root = ET.parse(path).getroot()
    return {e.attrib["key"]: e.attrib["value"] for e in root.findall("entry")}


@pytest.mark.parametrize("name", EXPORT_PRESETS)
def test_export_preset_writes_the_placement_record(name):
    """`.rsInfo` is the ONLY record of the export coordinate system, and the
    publish step cannot place a mesh without it. Turning
    MvsMeshExportInfoFile off would not fail the export - it would silently
    make every downstream upload unplaceable."""
    assert preset(name)["MvsMeshExportInfoFile"] == "true"


@pytest.mark.parametrize("name", EXPORT_PRESETS)
def test_export_preset_stays_georeferenced(name):
    assert preset(name)["MvsExportIsGeoreferenced"] == "0x1"


@pytest.mark.parametrize("name", EXPORT_PRESETS)
def test_export_preset_applies_no_hidden_shift_or_scale(name):
    """A non-zero MvsExportMove* or non-unit MvsExportScale* would move the
    geometry without touching the .rsInfo the placement is derived from, so
    the asset would land off by exactly that amount with nothing to show it."""
    values = preset(name)
    for axis in "XYZ":
        assert values[f"MvsExportMove{axis}"] == "0.0"
        assert values[f"MvsExportScale{axis}"] == "1.0"


def test_companions_follow_mtl_references_not_the_whole_folder(tmp_path):
    """Copying every texture in the folder would ship the unused by-parts set
    too - 326 MB against 74 MB on NA168 H2080."""
    from publish_cesium import referenced_companions
    obj = write(tmp_path, "m.obj", "mtllib m.mtl\nv 0 0 0\n")
    write(tmp_path, "m.mtl", "newmtl a\nmap_Kd m_diffuse.jpg\n")
    write(tmp_path, "m_diffuse.jpg", "x")
    write(tmp_path, "unrelated.jpg", "x")
    names = {p.name for p in referenced_companions([obj])}
    assert names == {"m.mtl", "m_diffuse.jpg"}
