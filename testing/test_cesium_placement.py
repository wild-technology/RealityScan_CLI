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
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

np = pytest.importorskip("numpy")

from modules.cesium_placement import (  # noqa: E402
    PlacementError, apply_interpretation, find_rsinfo, geoid_separation,
    msl_to_ellipsoidal, nav_envelope_from_flight_log, parse_rsinfo,
    read_obj_vertices, resolve_to_global, rewrite_obj_local, to_local_enu)

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
# local frame
# --------------------------------------------------------------------------

def test_to_local_enu_is_a_pure_translation():
    points = np.array([[348360.0, 396325.0, -580.0],
                       [348350.0, 396315.0, -600.0]])
    local = to_local_enu(points, (348355.0, 396320.0), -590.0)
    assert np.allclose(local, [[5.0, 5.0, 10.0], [-5.0, -5.0, -10.0]])
    # Shape-preserving: pairwise distances survive unchanged.
    assert np.linalg.norm(local[0] - local[1]) == pytest.approx(
        np.linalg.norm(points[0] - points[1]))


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
