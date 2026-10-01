"""The ion account audit - what it reads from a tileset.json, offline.

Traced to the 2026-10-01 decision prep. The audit judged each asset by the
centre of ``root.boundingVolume.box``, which on ion is the tiler's padded
octree root cell: a CUBE about as wide as the mesh's largest extent, whose
centre therefore rides (cube side - vertical extent) / 2 above the mesh.
On NA165/H2060 zone_1_c2 that was 16 m of a 25 m undulation, enough to
read "ok" on an asset that sits N too deep - and enough to make the audit
useless as the check on a re-placement. The geometry's real box is
``root.metadata.properties.tightBoundingBox``, which ``publish_cesium
--verify`` already decodes; these pin that the audit reads it through that
same decoder, reports both geometries side by side, and survives a tileset
that has no such property.

The second half is traced to the first live runs of that extended audit
(2026-10-01): a body that could not be decoded cost the whole run; point
clouds carry no tight box, so nothing gave ONE verdict per asset; the centre
rule called five assets FAULT that were plainly N too deep (and would call
them MISSING-GEOID once raised), because the median of all nav within 30 m
mixes passes; floor and top heights, N on an off-track centre and the link
from a tileset to its source had to be derived by hand; and the account
changed under the audit with no way to diff two reports.

The third part (marked "what the second review's mutants walked through")
is traced to that review, 2026-10-01: seven mutants of a correct validator
passed all 69 tests - ``extent_m`` taken from the tight box, the first
flight log instead of the nearest, the radius doubled, the geoid asked at
(lat, lon), pagination dropped, ``allow_ballpark=True``, assets unsorted -
and four small defects were left: a malformed ``--compare`` file crashed
after the whole audit and before the report was written, the endpoint's own
token was not scrubbed, the report did not state its signs and datums, and
NaN / Infinity could be written into it.

Hermetic: synthetic tileset JSON, a synthetic flight log, the geoid stubbed
to a known N, and - for the tests that run ``main()`` - a fake ``requests``
whose session has ``get`` and nothing else, so a write verb would be an
AttributeError. No network, no token, no grid.
"""
import json
import math
import os
import re
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

np = pytest.importorskip("numpy")
pytest.importorskip("pyproj")

import publish_cesium  # noqa: E402
import validate_cesium_assets as vca  # noqa: E402
from modules.cesium_placement import ecef_enu_rotation  # noqa: E402

# The NA165/H2060 site. E 710830 N 8428136 in UTM 2S is this lon/lat.
SITE_LON, SITE_LAT = -169.046249171, -14.210270179
SITE_EAST, SITE_NORTH = 710830.0, 8428136.0
NAV_ALT = -647.0          # cameras: -depth below the sea surface
STUB_N = 25.25            # exactly representable, so sums compare exactly
MESH_MID = -650.0         # an UNFIXED asset: the mesh at its -depth, no N

# A mesh 10 m E x 46 m N x 4 m Up about the local origin, and the cube ion
# wraps it in: side 46, sharing the mesh's floor, so its centre is 21 m up.
TIGHT = [0.0, 0.0, 0.0, 5.0, 0.0, 0.0, 0.0, 23.0, 0.0, 0.0, 0.0, 2.0]
CUBE = [0.0, 0.0, 21.0, 23.0, 0.0, 0.0, 0.0, 23.0, 0.0, 0.0, 0.0, 23.0]

VERDICTS = ("verdict", "tight_verdict", "best_verdict", "best_bracket_verdict")


def geoid_stub(lon, lat):
    return STUB_N


def to_geo():
    from pyproj import Transformer
    return Transformer.from_crs("EPSG:4978", "EPSG:4979", always_xy=True)


def enu_transform(lon, lat, h):
    """Column-major East-North-Up -> ECEF at a point: what ion writes into
    root.transform for a mesh uploaded with options.position."""
    from pyproj import Transformer
    origin = Transformer.from_crs("EPSG:4979", "EPSG:4978",
                                  always_xy=True).transform(lon, lat, h)
    east, north, up = (list(map(float, row))
                       for row in ecef_enu_rotation(lon, lat))
    return east + [0.0] + north + [0.0] + up + [0.0] + list(origin) + [1.0]


def mesh_tileset(h=MESH_MID, tight=TIGHT, cube=CUBE, lon=SITE_LON,
                 lat=SITE_LAT):
    root = {"transform": enu_transform(lon, lat, h),
            "boundingVolume": {"box": list(cube)},
            "metadata": {"class": "tile",
                         "properties": {"tightBoundingBox": list(tight)}}}
    return {"asset": {"version": "1.1"}, "root": root}


def cloud_tileset(h=MESH_MID):
    """A point cloud as ion tiles it: no metadata, and a root box that is
    the geometry's own box, not a padded cube."""
    tileset = mesh_tileset(h=h, cube=TIGHT)
    del tileset["root"]["metadata"]
    return tileset


def nav(tmp_path):
    """One zone-tagged flight log: a 9 x 9 lawn of cameras over the site."""
    from pyproj import Transformer
    lines = ["Name;X (East);Y (North);Alt;XA;YA;AA"]
    for i in range(-4, 5):
        for j in range(-4, 5):
            lines.append("f%d_%d.jpg;%.3f;%.3f;%.3f;10;10;1" % (
                i, j, SITE_EAST + 5.0 * i, SITE_NORTH + 5.0 * j, NAV_ALT))
    path = tmp_path / "flight_log_T_2L_UTM.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    crs = vca.utm_epsg(str(path))
    return [{"log": str(path), "crs": crs, "rows": vca.load_nav(str(path)),
             "fwd": Transformer.from_crs("EPSG:4326", crs, always_xy=True)}]


def audit(tileset, tmp_path, **kwargs):
    return vca.audit_tileset({}, tileset, nav(tmp_path), geoid_stub,
                             to_geo(), 30.0, 2.0, **kwargs)


# ------------------------------------------------------- the tight box decode

def test_the_tight_box_is_read_by_the_publishers_own_decoder():
    """One decoder, not two: the audit's extents ARE publish_cesium's."""
    tileset = mesh_tileset()
    geo = vca.decode_tileset(tileset)
    published = publish_cesium.decode_tileset_placement(tileset)
    assert geo["has_tight_box"] is True
    assert geo["tight_extent_m"] == published["extents_m"] == [10.0, 46.0, 4.0]
    assert geo["tight_box_centre_local_m"] == [0.0, 0.0, 0.0]
    assert geo["tight_box_half_axes_m"] == [[5.0, 0.0, 0.0], [0.0, 23.0, 0.0],
                                            [0.0, 0.0, 2.0]]


def test_the_root_box_extents_are_recorded_not_just_its_centre():
    geo = vca.decode_tileset(mesh_tileset())
    assert geo["extent_m"] == [46.0, 46.0, 46.0]          # a cube: the root cell
    assert geo["radius_m"] == pytest.approx(math.sqrt(3) * 23.0)
    assert geo["root_box_centre_local_m"] == [0.0, 0.0, 21.0]
    assert geo["root_box_half_axes_m"] == [[23.0, 0.0, 0.0], [0.0, 23.0, 0.0],
                                           [0.0, 0.0, 23.0]]


def test_the_tight_centre_is_carried_through_the_root_transform(tmp_path):
    """A tight box centred 3 m east, 4 m south and 1.5 m above the local
    origin: the centre is origin + 3 E - 4 N + 1.5 Up in ECEF, so its
    ellipsoidal height is the origin's plus 1.5 m."""
    tight = [3.0, -4.0, 1.5] + TIGHT[3:]
    tileset = mesh_tileset(tight=tight)
    transform = tileset["root"]["transform"]
    east, north, up = (np.array(transform[i:i + 3]) for i in (0, 4, 8))
    expected = np.array(transform[12:15]) + 3.0 * east - 4.0 * north + 1.5 * up
    geo = vca.decode_tileset(tileset)
    assert np.allclose(geo["tight_centre_ecef"], expected, atol=1e-6)

    rec = audit(tileset, tmp_path)
    assert rec["tight_height_ellipsoidal_m"] == pytest.approx(MESH_MID + 1.5,
                                                              abs=1e-3)
    assert rec["tight_lon"] > SITE_LON and rec["tight_lat"] < SITE_LAT
    assert rec["tight_extent_m"] == [10.0, 46.0, 4.0]


# ------------------------------------------------------------ the two verdicts

def test_the_cube_centre_reads_ok_where_the_tight_centre_shows_the_missing_geoid(tmp_path):
    """The zone_1_c2 artefact. The mesh sits 3 m under its cameras with NO
    geoid applied, i.e. N too deep. The cube centre is 21 m above the mesh,
    which eats most of N and reads "ok"; the tight centre reads the truth.
    The old verdict is kept as it was - that is what keeps old reports
    comparable - and the new one stands beside it."""
    rec = audit(mesh_tileset(), tmp_path)

    assert rec["height_ellipsoidal_m"] == pytest.approx(MESH_MID + 21.0, abs=1e-3)
    assert rec["vertical_vs_cameras_m"] == pytest.approx(21.0 - 3.0 - STUB_N, abs=1e-3)
    assert rec["verdict"] == "ok"
    assert rec["verdict_geometry"] == "root.boundingVolume.box centre"

    assert rec["tight_height_ellipsoidal_m"] == pytest.approx(MESH_MID, abs=1e-3)
    assert rec["tight_vertical_vs_cameras_m"] == pytest.approx(-3.0 - STUB_N, abs=1e-3)
    assert rec["tight_verdict"] == "MISSING-GEOID"
    assert rec["tight_verdict_geometry"] == (
        "root.metadata.properties.tightBoundingBox centre")
    assert rec["root_centre_above_tight_centre_m"] == pytest.approx(21.0, abs=1e-3)

    # Both centres were matched to the same dive and the same cameras.
    assert rec["dive_log"] == rec["tight_dive_log"] == "flight_log_T_2L_UTM.txt"
    assert rec["geoid_n_m"] == rec["tight_geoid_n_m"] == STUB_N
    assert rec["nav_alt_median_m"] == rec["tight_nav_alt_median_m"] == NAV_ALT
    assert rec["nav_rows_in_radius"] > 0
    assert rec["nav_alt_min_m"] == rec["nav_alt_max_m"] == NAV_ALT


def test_a_correct_raise_is_confirmed_by_the_tight_verdict(tmp_path):
    """After +N the mesh is 3 m under its cameras on the right datum. The
    tight centre says ok; the cube centre, 21 m higher, cries FAULT - which
    is why the old verdict could not confirm a re-placement."""
    rec = audit(mesh_tileset(h=MESH_MID + STUB_N), tmp_path)
    assert rec["tight_verdict"] == "ok"
    assert rec["tight_vertical_vs_cameras_m"] == pytest.approx(-3.0, abs=1e-3)
    assert "tight_why" not in rec
    assert rec["verdict"] == "FAULT"
    assert rec["vertical_vs_cameras_m"] == pytest.approx(18.0, abs=1e-3)


@pytest.mark.parametrize("dv, verdict", [
    (-25.25, "MISSING-GEOID"),      # exactly N under the cameras
    (-12.7, "MISSING-GEOID"),       # just inside N/2 of -N
    (-12.5, "ok"),                  # just above -N/2
    (-3.0, "ok"),
    (9.9, "ok"),
    (10.0, "FAULT"),                # at or above +10 m: too high
    (-38.0, "FAULT"),               # more than N/2 beyond -N
])
def test_the_verdict_rule_is_the_2026_09_30_rule(dv, verdict):
    """Pinned so the root-box verdict stays comparable with saved reports."""
    got, why = vca.classify(dv, STUB_N)
    assert got == verdict
    assert (why is None) == (verdict == "ok")


# ------------------------------------------------------------ no tight box

def _without(mutate):
    tileset = mesh_tileset()
    mutate(tileset["root"])
    return tileset


NO_TIGHT_BOX = {
    "no metadata at all (a point cloud)": lambda root: root.pop("metadata"),
    "metadata is null": lambda root: root.update(metadata=None),
    "no properties": lambda root: root["metadata"].pop("properties"),
    "another property only": lambda root: root["metadata"].update(
        properties={"other": 1}),
    "eleven numbers": lambda root: root["metadata"]["properties"].update(
        tightBoundingBox=TIGHT[:11]),
    "not numeric": lambda root: root["metadata"]["properties"].update(
        tightBoundingBox=["x"] * 12),
    "non-finite": lambda root: root["metadata"]["properties"].update(
        tightBoundingBox=[float("nan")] * 12),
    # float() would take both of these; a box is JSON numbers or it is not one.
    "numbers as strings": lambda root: root["metadata"]["properties"].update(
        tightBoundingBox=[str(v) for v in TIGHT]),
    "booleans": lambda root: root["metadata"]["properties"].update(
        tightBoundingBox=[True] * 12),
}


@pytest.mark.parametrize("case", sorted(NO_TIGHT_BOX))
def test_a_tileset_without_a_tight_box_is_recorded_not_fatal(case, tmp_path):
    rec = audit(_without(NO_TIGHT_BOX[case]), tmp_path)
    assert rec["has_tight_box"] is False
    assert rec["tight_verdict"] == "no-tight-box"
    assert rec["tight_why"]                       # says why it is absent
    assert rec["tight_verdict_geometry"] is None
    assert "tight_height_ellipsoidal_m" not in rec
    assert "tight_extent_m" not in rec
    # ... and the root-box audit is untouched by the absence.
    assert rec["verdict"] == "ok"
    assert rec["extent_m"] == [46.0, 46.0, 46.0]
    assert rec["height_ellipsoidal_m"] == pytest.approx(MESH_MID + 21.0, abs=1e-3)


def test_no_root_transform_is_still_a_fault(tmp_path):
    tileset = mesh_tileset()
    del tileset["root"]["transform"]
    rec = audit(tileset, tmp_path)
    assert rec["has_root_transform"] is False
    assert rec["verdict"] == rec["tight_verdict"] == rec["best_verdict"] == "FAULT"
    assert rec["why"].startswith("no root.transform")
    assert rec["best_bracket_verdict"] == "not-assessed"
    assert "lon" not in rec and "tight_lon" not in rec
    assert rec["tight_extent_m"] == [10.0, 46.0, 4.0]    # still recorded


# ------------------------------------------------------------- the local frame

def test_an_enu_frame_makes_the_extents_east_north_up(tmp_path):
    rec = audit(mesh_tileset(), tmp_path)
    assert rec["local_axes_off_enu_deg"] < 1e-3
    assert rec["local_axes_scale"] == pytest.approx([1.0, 1.0, 1.0])
    assert rec["tight_extent_enu_m"] == pytest.approx([10.0, 46.0, 4.0], abs=1e-6)


def test_a_frame_that_is_not_enu_is_flagged_and_its_true_span_reported(tmp_path):
    """Local X = North, local Y = -East (a quarter turn about Up). The box
    still lists 10 x 46 x 4 along its OWN axes, but on the ground that is
    46 m east-west by 10 m north-south - and the report must say so rather
    than label the raw numbers E x N x U."""
    tileset = mesh_tileset()
    t = tileset["root"]["transform"]
    east, north = t[0:3], t[4:7]
    t[0:3] = north
    t[4:7] = [-c for c in east]
    rec = audit(tileset, tmp_path)
    assert rec["local_axes_off_enu_deg"] == pytest.approx(90.0, abs=1e-3)
    assert rec["tight_extent_m"] == [10.0, 46.0, 4.0]
    assert rec["tight_extent_enu_m"] == pytest.approx([46.0, 10.0, 4.0], abs=1e-6)


# ------------------------------------------------------- floor, top and "best"

def test_floor_and_top_are_reported_for_both_boxes(tmp_path):
    """Centre minus / plus half the span along Up. The cube shares the
    mesh's floor - that is what makes its centre ride high - and its top is
    42 m above the mesh's."""
    rec = audit(mesh_tileset(), tmp_path)
    assert rec["tight_floor_height_ellipsoidal_m"] == pytest.approx(MESH_MID - 2.0, abs=1e-3)
    assert rec["tight_top_height_ellipsoidal_m"] == pytest.approx(MESH_MID + 2.0, abs=1e-3)
    assert rec["floor_height_ellipsoidal_m"] == pytest.approx(MESH_MID - 2.0, abs=1e-3)
    assert rec["top_height_ellipsoidal_m"] == pytest.approx(MESH_MID + 44.0, abs=1e-3)
    assert rec["extent_enu_m"] == pytest.approx([46.0, 46.0, 46.0], abs=1e-6)


def test_floor_and_top_follow_the_frame_not_the_box_order(tmp_path):
    """A frame whose local Z is NOT Up (X = Up, Z = East): the vertical
    span is the box's FIRST extent, and floor and top must use that."""
    tileset = mesh_tileset()
    t = tileset["root"]["transform"]
    east, up = t[0:3], t[8:11]
    t[0:3], t[8:11] = up, east
    rec = audit(tileset, tmp_path)
    assert rec["tight_extent_enu_m"] == pytest.approx([4.0, 46.0, 10.0], abs=1e-6)
    assert (rec["tight_top_height_ellipsoidal_m"]
            - rec["tight_floor_height_ellipsoidal_m"]) == pytest.approx(10.0, abs=1e-6)


def test_best_is_the_tight_box_on_a_mesh(tmp_path):
    rec = audit(mesh_tileset(), tmp_path)
    assert rec["best_geometry"] == "root.metadata.properties.tightBoundingBox"
    assert rec["best_verdict"] == rec["tight_verdict"] == "MISSING-GEOID"
    assert rec["best_why"] == rec["tight_why"]
    for key in ("lon", "lat", "height_ellipsoidal_m", "geoid_n_m",
                "floor_height_ellipsoidal_m", "top_height_ellipsoidal_m",
                "extent_enu_m", "vertical_vs_cameras_m", "nav_alt_median_m",
                "dive_log", "distance_to_track_m", "expected_height_m"):
        assert rec["best_" + key] == rec["tight_" + key], key
    assert rec["best_height_ellipsoidal_m"] != rec["height_ellipsoidal_m"]


def test_best_is_the_root_box_on_a_point_cloud(tmp_path):
    """No tileset tiled from a point cloud carries a tight box (0 of 47 on
    the live account, 2026-10-01 15:00 UTC; 42 of them the H2060 dense
    clouds): their one verdict has to come from the root box, not be
    "no-tight-box"."""
    rec = audit(cloud_tileset(), tmp_path)
    assert rec["tight_verdict"] == "no-tight-box"
    assert rec["best_geometry"] == "root.boundingVolume.box"
    assert rec["best_verdict"] == rec["verdict"] == "MISSING-GEOID"
    assert rec["best_height_ellipsoidal_m"] == rec["height_ellipsoidal_m"]
    assert rec["best_floor_height_ellipsoidal_m"] == pytest.approx(MESH_MID - 2.0, abs=1e-3)
    assert rec["best_top_height_ellipsoidal_m"] == pytest.approx(MESH_MID + 2.0, abs=1e-3)
    assert rec["best_bracket_verdict"] == "MISSING-GEOID"


def test_a_tileset_with_no_box_at_all_says_what_its_centre_is(tmp_path):
    tileset = cloud_tileset()
    del tileset["root"]["boundingVolume"]
    rec = audit(tileset, tmp_path)
    assert rec["verdict_geometry"] == rec["best_geometry"] == (
        "root.transform origin (no root box)")
    assert "floor_height_ellipsoidal_m" not in rec
    assert rec["best_bracket_verdict"] == "not-assessed"
    assert rec["best_bracket_why"] == "no box extents"


# ----------------------------------------------------------- the bracket test

def test_the_bracket_test_reads_missing_geoid_then_ok_after_the_raise(tmp_path):
    """Cameras 1 m above the mesh's top. Unfixed, they fit between floor and
    top only when N is left out; raised by N they fit with it."""
    unfixed = audit(mesh_tileset(), tmp_path, margin_m=7.0)
    assert unfixed["best_bracket_verdict"] == "MISSING-GEOID"
    assert unfixed["best_cameras_above_top_m"] == pytest.approx(1.0 + STUB_N, abs=1e-3)
    assert unfixed["best_cameras_above_floor_m"] == pytest.approx(5.0 + STUB_N, abs=1e-3)
    assert "N too deep" in unfixed["best_bracket_why"]
    # footprint 10 x 46 m + 7 m: five columns of the 5 m lawn, all nine rows
    assert unfixed["best_footprint_nav_rows"] == 45
    assert unfixed["best_footprint_nav_alt_median_m"] == NAV_ALT
    assert (unfixed["best_footprint_nav_alt_min_m"]
            == unfixed["best_footprint_nav_alt_max_m"] == NAV_ALT)

    raised = audit(mesh_tileset(h=MESH_MID + STUB_N), tmp_path)
    assert raised["best_bracket_verdict"] == "ok"
    assert raised["best_cameras_above_top_m"] == pytest.approx(1.0, abs=1e-3)
    assert "best_bracket_why" not in raised


def test_the_bracket_test_takes_the_cameras_over_the_footprint_only(tmp_path):
    """A 2 x 2 m model with no margin has one camera of the lawn over it;
    the centre rule's 30 m radius takes every one."""
    small = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 2.0]
    rec = audit(mesh_tileset(tight=small), tmp_path, margin_m=0.0)
    assert rec["best_footprint_nav_rows"] == 1
    assert rec["tight_nav_rows_in_radius"] > 40


def test_a_box_taller_than_n_cannot_be_told_and_says_so(tmp_path):
    """A 40 m wall: the cameras sit inside its height with N and without."""
    wall = [0.0, 0.0, 0.0, 5.0, 0.0, 0.0, 0.0, 23.0, 0.0, 0.0, 0.0, 20.0]
    rec = audit(mesh_tileset(h=-640.0, tight=wall), tmp_path)
    assert rec["best_bracket_verdict"] == "ambiguous"
    assert "with N and without it" in rec["best_bracket_why"]


def test_the_bracket_test_faults_a_model_nowhere_near_its_cameras(tmp_path):
    rec = audit(mesh_tileset(h=-500.0), tmp_path)
    assert rec["best_bracket_verdict"] == "FAULT"
    assert rec["best_verdict"] == "FAULT"


def _track(alt=-100.0):
    return {"east": 0.0, "north": 0.0, "distance_m": 0.0,
            "nav": {"log": "x", "rows": [(0.0, 0.0, alt)]}, "d2": [(0.0, alt)]}


@pytest.mark.parametrize("floor, top, verdict", [
    (-80.0, -70.0, "ok"),              # cameras (-75 with N) inside the box
    (-80.0, -85.0 + 1e-9, "ok"),       # ... and up to 10 m above its top
    (-80.0, -85.0, "ok"),              # exactly 10 m above: still its cameras
    (-95.0, -85.1, "FAULT"),           # more than 10 m above the top
    (-75.0, -70.0, "FAULT"),           # AT the floor is not above it
    (-105.0, -95.0, "MISSING-GEOID"),  # fits only if N is left out
    (-110.0, -70.0, "ambiguous"),      # fits both ways
])
def test_the_bracket_rule(floor, top, verdict):
    """Cameras at Alt -100 with N = 25, i.e. at -75 on the ellipsoid."""
    out = vca.bracket(_track(), 25.0, floor, top, 1.0, 1.0)
    assert out["bracket_verdict"] == verdict
    assert out["cameras_above_top_m"] == pytest.approx(-75.0 - top)
    assert out["cameras_above_floor_m"] == pytest.approx(-75.0 - floor)
    assert ("bracket_why" in out) == (verdict != "ok")


def test_the_bracket_margins_are_arguments():
    track = _track()
    track["nav"]["rows"] = [(8.0, 0.0, -100.0)]
    assert vca.bracket(track, 25.0, -80.0, -70.0, 1.0, 1.0,
                       margin_m=5.0)["bracket_verdict"] == "no-nav"
    assert vca.bracket(track, 25.0, -80.0, -70.0, 1.0, 1.0,
                       margin_m=7.0)["bracket_verdict"] == "ok"
    assert vca.bracket(_track(), 25.0, -95.0, -90.0, 1.0, 1.0,
                       above_top_m=10.0)["bracket_verdict"] == "FAULT"
    assert vca.bracket(_track(), 25.0, -95.0, -90.0, 1.0, 1.0,
                       above_top_m=15.0)["bracket_verdict"] == "ok"


# ----------------------------------------------- a centre off the nav track

def test_an_off_track_centre_still_carries_n(tmp_path):
    """H2063 c22's root-box centre sat 32 m from the track: "FAULT, 32 m
    from the nav track" - and the row had no geoid_n_m, so N had to be
    recomputed outside the tool for a uniform table."""
    rec = audit(cloud_tileset(), tmp_path)        # control: on the track
    assert rec["geoid_n_m"] == STUB_N and "nav_alt_median_m" in rec

    off = mesh_tileset(lon=SITE_LON + 0.001)      # ~108 m east of the lawn
    rec = audit(off, tmp_path)
    assert rec["verdict"] == rec["tight_verdict"] == "FAULT"
    assert re.fullmatch(r"\d+ m from the nav track", rec["why"])
    assert rec["geoid_n_m"] == rec["tight_geoid_n_m"] == rec["best_geoid_n_m"] == STUB_N
    assert "nav_alt_median_m" not in rec and "vertical_vs_cameras_m" not in rec
    assert rec["best_bracket_verdict"] == "no-nav"


def test_an_unmatched_asset_is_not_assessed_and_asks_no_geoid(tmp_path):
    def no_geoid(lon, lat):
        raise AssertionError("the geoid is not needed for an unmatched asset")

    far = mesh_tileset(lon=SITE_LON + 1.0)        # ~108 km away
    rec = vca.audit_tileset({}, far, nav(tmp_path), no_geoid, to_geo(),
                            30.0, 2.0)
    assert rec["verdict"] == rec["tight_verdict"] == rec["best_verdict"] == "unmatched"
    assert rec["best_bracket_verdict"] == "not-assessed"
    assert "km from every nav track" in rec["best_bracket_why"]
    assert "geoid_n_m" not in rec


# --------------------------------------- a body that cannot be decoded at all

def _spoil(mutate):
    tileset = mesh_tileset()
    mutate(tileset["root"])
    return tileset


UNDECODABLE = {
    "the body is a list": lambda: [1, 2, 3],
    "the body is null": lambda: None,
    "the body is a string": lambda: "<html>Bad Gateway</html>",
    "the root box holds nulls": lambda: _spoil(
        lambda root: root["boundingVolume"].update(box=[None] * 12)),
    "the root box holds strings": lambda: _spoil(
        lambda root: root["boundingVolume"].update(box=["a"] * 12)),
    "boundingVolume is a list": lambda: _spoil(
        lambda root: root.update(boundingVolume=[1])),
    "the transform holds nulls": lambda: _spoil(
        lambda root: root.update(transform=[None] * 16)),
    "the transform holds strings": lambda: _spoil(
        lambda root: root.update(transform=["a"] * 16)),
    "root is a list": lambda: {"root": [1, 2]},
}


@pytest.mark.parametrize("case", sorted(UNDECODABLE))
def test_a_tileset_that_cannot_be_decoded_is_unreadable_and_the_audit_goes_on(
        case, tmp_path):
    """The report is written at the END of the run. At 35e3ca6 the decode
    sat inside the try; the first refactor moved it out, so one bad body
    cost the whole audit. It is one "unreadable" row, never a half-filled
    one, and the next asset is still audited."""
    assets = [{"id": 1, "name": "bad", "type": "3DTILES", "status": "COMPLETE"},
              {"id": 2, "name": "good", "type": "3DTILES", "status": "COMPLETE"}]
    tilesets = {1: UNDECODABLE[case](), 2: mesh_tileset()}
    bad, good = vca.audit_assets(assets, tilesets.__getitem__, nav(tmp_path),
                                 geoid_stub, to_geo(), 30.0, 2.0)
    assert [bad[key] for key in VERDICTS] == ["unreadable"] * 4
    assert bad["why"]
    assert sorted(bad) == sorted(
        ["asset_id", "name", "type", "status", "date_added", "bytes", "why",
         "source_asset_id", "source_pairing"] + list(VERDICTS))
    assert good["verdict"] == "ok" and good["tight_verdict"] == "MISSING-GEOID"


def test_a_body_that_is_not_a_json_object_is_called_that():
    with pytest.raises(vca.Unreadable, match="a list, not a JSON object"):
        vca.decode_tileset([1, 2, 3])
    with pytest.raises(vca.Unreadable, match="a NoneType, not a JSON object"):
        vca.decode_tileset(None)


def test_a_failure_after_the_decode_leaves_no_half_filled_row(tmp_path):
    """The body decodes, then something later fails for this one asset. A
    row that kept the decoded extents under an "unreadable" verdict would
    read as audited."""
    def flaky(lon, lat):
        raise RuntimeError("grid read failed")

    assets = [{"id": 2, "name": "good", "type": "3DTILES", "status": "COMPLETE"}]
    (row,) = vca.audit_assets(assets, lambda i: mesh_tileset(), nav(tmp_path),
                              flaky, to_geo(), 30.0, 2.0)
    assert [row[key] for key in VERDICTS] == ["unreadable"] * 4
    assert row["why"] == "RuntimeError: grid read failed"
    assert "extent_m" not in row and "has_root_transform" not in row
    assert "lon" not in row and "best_geometry" not in row


def test_a_geoid_that_cannot_be_used_still_stops_the_run(tmp_path):
    """The one thing that must NOT become an "unreadable" row."""
    def unusable(lon, lat):
        raise SystemExit("the geoid grid is not usable")

    assets = [{"id": 2, "name": "good", "type": "3DTILES", "status": "COMPLETE"}]
    with pytest.raises(SystemExit, match="not usable"):
        vca.audit_assets(assets, lambda i: mesh_tileset(), nav(tmp_path),
                         unusable, to_geo(), 30.0, 2.0)


def test_explain_names_the_exception_and_scrubs_before_it_cuts():
    assert vca.explain(KeyError("url")) == "KeyError: 'url'"     # not "'url'"
    assert vca.explain(vca.Unreadable("no tileset")) == "no tileset"
    # the secret straddles the 160-character cut: cutting first would leave
    # a piece of it that no longer matches and is kept
    long = vca.explain(RuntimeError("x" * 135 + " s3cret-token"),
                       ("s3cret-token",))
    assert len(long) <= 160 and "s3cret" not in long
    assert long.endswith("<redacted>")


# ------------------------------------------------------- the listing fields

def test_listing_fields_are_carried_and_description_only_when_present():
    full = vca.asset_fields({"id": 7, "name": "n", "type": "3DTILES",
                             "status": "COMPLETE", "bytes": 1234,
                             "dateAdded": "2026-09-27T03:11:00.000Z",
                             "description": "L run"})
    assert full == {"asset_id": 7, "name": "n", "type": "3DTILES",
                    "status": "COMPLETE", "bytes": 1234,
                    "date_added": "2026-09-27T03:11:00.000Z",
                    "description": "L run"}
    bare = vca.asset_fields({"id": 8, "name": "m", "type": "3DTILES",
                             "status": "COMPLETE", "description": ""})
    assert "description" not in bare
    assert bare["date_added"] is None and bare["bytes"] is None


def test_a_tileset_is_linked_to_the_source_it_was_tiled_from():
    """``bytes`` on a tileset is the TILED size; the uploaded size is on the
    source collection, which ion does not link. Paired by id and name, said
    per row, and never guessed where a name is shared."""
    rows = [
        {"asset_id": 10, "name": "a", "type": "MESH_COLLECTION", "bytes": 100},
        {"asset_id": 11, "name": "a", "type": "3DTILES", "bytes": 7},
        {"asset_id": 20, "name": "old", "type": "3DTILES", "bytes": 5},
        {"asset_id": 500, "name": "old", "type": "POINT_CLOUD_COLLECTION",
         "bytes": 50},
        {"asset_id": 30, "name": "source deleted", "type": "3DTILES"},
        {"asset_id": 40, "name": "twice", "type": "3DTILES"},
        {"asset_id": 45, "name": "twice", "type": "3DTILES"},
        {"asset_id": 600, "name": "twice", "type": "MESH_COLLECTION"},
        {"asset_id": 49, "name": "another upload", "type": "MESH_COLLECTION"},
        {"asset_id": 50, "name": "not its tileset", "type": "3DTILES"},
        {"asset_id": 60, "name": "terrain", "type": "TERRAIN"},
    ]
    by_id = {r["asset_id"]: r for r in vca.pair_sources(rows)}

    assert by_id[11]["source_asset_id"] == 10
    assert by_id[11]["source_bytes"] == 100
    assert by_id[11]["source_type"] == "MESH_COLLECTION"
    assert by_id[11]["source_pairing"] == "the asset one id below, same name"
    assert by_id[10]["tileset_asset_id"] == 11

    assert by_id[20]["source_asset_id"] == 500           # a migrated source
    assert by_id[20]["source_pairing"] == "the only collection of that name"
    assert by_id[500]["tileset_asset_id"] == 20

    assert by_id[30]["source_asset_id"] is None
    assert by_id[30]["source_pairing"] == "no source collection left"

    for i in (40, 45):                                   # two tilesets, one source
        assert by_id[i]["source_asset_id"] is None
        assert by_id[i]["source_pairing"].startswith("not paired: 3 assets")
    assert "tileset_asset_id" not in by_id[600]

    assert by_id[50]["source_asset_id"] is None          # adjacent, other name
    assert "tileset_asset_id" not in by_id[49]
    assert "source_asset_id" not in by_id[60]            # nothing to say


def test_scrub_removes_the_token_and_anything_shaped_like_one():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJqdGkiOiJhYmMifQ.c2lnbmF0dXJl"
    text = vca.scrub("401 for Bearer s3cret at host; also %s" % jwt, ("s3cret",))
    assert "s3cret" not in text and jwt not in text
    assert text.count("<redacted>") == 2


def test_zone_tag_gives_the_utm_epsg():
    assert vca.utm_epsg("flight_log_NA165_H2060_2L_UTM.txt") == "EPSG:32702"
    assert vca.utm_epsg("flight_log_NA168_H2077_53N_UTM.txt") == "EPSG:32653"
    assert vca.utm_epsg("flight_log_NA168_H2082_52N_UTM.txt") == "EPSG:32652"
    with pytest.raises(SystemExit, match="no UTM zone tag"):
        vca.utm_epsg("flight_log.txt")


def test_a_non_finite_undulation_stops_the_audit(monkeypatch):
    """A missing grid with PROJ network on and the CDN unreachable comes
    back as inf (BUGS.md B26). Every verdict would be garbage."""
    import pyproj

    class Unreachable:
        def transform(self, lon, lat, z):
            return lon, lat, float("inf")

    monkeypatch.setattr(pyproj.Transformer, "from_crs",
                        staticmethod(lambda *a, **k: Unreachable()))
    with pytest.raises(SystemExit, match="geoid grid is not usable"):
        vca.geoid_lookup()(SITE_LON, SITE_LAT)


# ------------------------------------------------- against a previous report

def test_compare_lists_what_is_gone_new_and_changed():
    """The account went 365 -> 359 -> 361 -> 371 assets in two and a half
    hours on 2026-10-01; the deletions were found by diffing JSON by hand."""
    previous = {"schema": 2, "generated": "2026-10-01 10:24:26", "assets": [
        {"asset_id": 1, "name": "stays", "type": "3DTILES", "status": "COMPLETE",
         "bytes": 5, "verdict": "MISSING-GEOID", "tight_verdict": "MISSING-GEOID",
         "height_ellipsoidal_m": -650.0, "date_added": "2026-09-27T00:00:00.000Z"},
        {"asset_id": 2, "name": "deleted", "type": "3DTILES", "status": "COMPLETE",
         "bytes": 9, "verdict": "ok", "date_added": "2026-09-27T00:00:01.000Z"},
        {"asset_id": 3, "name": "raised", "type": "3DTILES", "status": "COMPLETE",
         "bytes": 6, "verdict": "MISSING-GEOID", "tight_verdict": "MISSING-GEOID",
         "height_ellipsoidal_m": -650.0},
    ]}
    rows = [
        {"asset_id": 1, "name": "stays", "type": "3DTILES", "status": "COMPLETE",
         "bytes": 5, "verdict": "MISSING-GEOID", "tight_verdict": "MISSING-GEOID",
         "height_ellipsoidal_m": -650.0 + 1e-5,          # float noise: no change
         "best_verdict": "MISSING-GEOID"},               # a field 2 never had
        {"asset_id": 3, "name": "raised", "type": "3DTILES", "status": "COMPLETE",
         "bytes": 6, "verdict": "FAULT", "tight_verdict": "ok",
         "height_ellipsoidal_m": -624.75},
        {"asset_id": 4, "name": "uploaded", "type": "3DTILES",
         "status": "IN_PROGRESS", "bytes": 0,
         "date_added": "2026-10-01T13:32:00.000Z"},
    ]
    changes = vca.compare_reports(previous, rows)
    assert changes["previous_generated"] == "2026-10-01 10:24:26"
    assert (changes["previous_assets"], changes["assets"]) == (3, 3)
    assert [r["asset_id"] for r in changes["gone"]] == [2]
    assert changes["gone"][0]["name"] == "deleted"
    assert changes["gone"][0]["date_added"] == "2026-09-27T00:00:01.000Z"
    assert [r["asset_id"] for r in changes["new"]] == [4]
    assert changes["changed"] == [{
        "asset_id": 3, "name": "raised",
        "was": {"verdict": "MISSING-GEOID", "tight_verdict": "MISSING-GEOID",
                "height_ellipsoidal_m": -650.0},
        "now": {"verdict": "FAULT", "tight_verdict": "ok",
                "height_ellipsoidal_m": -624.75}}]


def test_compare_reads_a_schema_1_report_without_crying_wolf():
    """The 2026-09-30 report: {"assets": [...]} and four listing fields.
    What it never wrote is not a change."""
    previous = {"assets": [{"asset_id": 1, "name": "a", "type": "3DTILES",
                            "status": "COMPLETE", "verdict": "ok"}]}
    rows = [{"asset_id": 1, "name": "a", "type": "3DTILES",
             "status": "COMPLETE", "verdict": "ok", "bytes": 5,
             "tight_verdict": "MISSING-GEOID", "best_verdict": "MISSING-GEOID"}]
    changes = vca.compare_reports(previous, rows)
    assert changes["previous_schema"] == 1 and changes["previous_generated"] is None
    assert changes["gone"] == changes["new"] == changes["changed"] == []


# ----------------------------------------------------------- main(), GET only

SECRET = "ION-ACCOUNT-TOKEN-must-never-be-printed"
ASSET_TOKEN = "ASSET-ENDPOINT-TOKEN-must-never-be-printed"
THIRD_PARTY_KEY = "THIRD-PARTY-KEY-must-never-be-printed"


class FakeResponse:
    def __init__(self, payload, http_error=None):
        self._payload = payload
        self._http_error = http_error

    def raise_for_status(self):
        if self._http_error:
            raise RuntimeError(self._http_error)

    def json(self):
        return self._payload


def fake_requests(listing, details, tilesets, broken=(), endpoints=None,
                  http_errors=None, tileset_refused=()):
    """A ``requests`` whose Session can GET and do nothing else.

    ``endpoints`` replaces an asset's endpoint body; ``http_errors`` makes
    its tileset GET an HTTP error that still has a JSON body;
    ``tileset_refused`` makes it raise with BOTH tokens in the message.
    """
    calls = []
    endpoints, http_errors = endpoints or {}, http_errors or {}

    class Session:
        def get(self, url, headers=None, params=None, timeout=None):
            calls.append((url, dict(headers or {}), dict(params or {})))
            api = vca.API + "/v1/assets"
            if url == api:
                return FakeResponse(
                    {"items": listing if params["page"] == 1 else []})
            if url.startswith(api + "/") and url.endswith("/endpoint"):
                asset_id = int(url.split("/")[-2])
                if asset_id in broken:
                    raise RuntimeError("endpoint refused Bearer " + SECRET)
                if asset_id in endpoints:
                    return FakeResponse(endpoints[asset_id])
                return FakeResponse({
                    "url": "https://assets.example/%d/tileset.json" % asset_id,
                    "accessToken": ASSET_TOKEN})
            if url.startswith(api + "/"):
                return FakeResponse(details[int(url.split("/")[-1])])
            if url.startswith("https://assets.example/"):
                asset_id = int(url.split("/")[-2])
                if asset_id in tileset_refused:
                    raise RuntimeError(
                        "tileset host refused %s (account %s)"
                        % (headers["Authorization"], "Bearer " + SECRET))
                if asset_id in http_errors:
                    return FakeResponse({"code": "NotFound", "message": "gone"},
                                        http_errors[asset_id])
                return FakeResponse(tilesets[asset_id])
            raise AssertionError("unexpected request: %s" % url)

    return types.SimpleNamespace(Session=Session), calls


def run_main(tmp_path, monkeypatch, capsys, fake, extra=()):
    """``main()`` against a fake ``requests``: (report, console text)."""
    monkeypatch.setitem(sys.modules, "requests", fake)
    monkeypatch.setattr(vca, "geoid_lookup", lambda: geoid_stub)
    monkeypatch.setenv("CESIUM_ION_TOKEN", SECRET)
    log = nav(tmp_path)[0]["log"]
    out = tmp_path / "audit.json"
    monkeypatch.setattr(sys, "argv", ["validate_cesium_assets.py",
                                      "--flight-log", log, "--out", str(out)]
                        + list(extra))
    assert vca.main() == 0
    printed = "".join(capsys.readouterr())
    written = out.read_text(encoding="utf-8")
    for secret in (SECRET, ASSET_TOKEN, THIRD_PARTY_KEY):
        assert secret not in printed
        assert secret not in written
    assert printed.isascii()
    return json.loads(written), printed


def test_main_reads_with_get_only_and_never_prints_a_token(
        tmp_path, monkeypatch, capsys):
    listing = [
        {"id": 21, "name": "c2", "type": "MESH_COLLECTION",
         "status": "COMPLETE", "bytes": 4620000000,
         "dateAdded": "2026-09-27T03:10:00.000Z", "description": ""},
        {"id": 22, "name": "c2", "type": "3DTILES", "status": "COMPLETE",
         "bytes": 912345678, "dateAdded": "2026-09-27T03:11:00.000Z",
         "description": "L run"},
        # No dateAdded / bytes on the listing row: asked for individually.
        {"id": 23, "name": "c2 dense", "type": "3DTILES", "status": "COMPLETE"},
        {"id": 24, "name": "tiling", "type": "3DTILES",
         "status": "IN_PROGRESS", "bytes": 0,
         "dateAdded": "2026-10-01T07:00:00.000Z"},
        {"id": 25, "name": "broken", "type": "3DTILES", "status": "COMPLETE",
         "bytes": 1, "dateAdded": "2026-10-01T07:01:00.000Z"},
    ]
    details = {23: {"id": 23, "bytes": 555, "description": "dense cloud",
                    "dateAdded": "2026-10-01T06:00:00.000Z"}}
    fake, calls = fake_requests(listing, details,
                                {22: mesh_tileset(), 23: cloud_tileset()},
                                broken={25})
    report, printed = run_main(tmp_path, monkeypatch, capsys, fake)

    # The account token goes to api.cesium.com, the endpoint's own token to
    # the tileset host - and the one per-asset detail GET is for 23 alone.
    api_calls = [c for c in calls if c[0].startswith(vca.API)]
    assert all(c[1] == {"Authorization": "Bearer " + SECRET} for c in api_calls)
    tile_calls = [c for c in calls if c[0].startswith("https://assets.example/")]
    assert [c[1] for c in tile_calls] == [
        {"Authorization": "Bearer " + ASSET_TOKEN}] * 2
    assert [c[0] for c in calls if c[0].split("/")[-1].isdigit()] == [
        vca.API + "/v1/assets/23"]

    assert report["schema"] == 3
    # the signs and datums travel with the numbers, not only in a docstring
    assert report["conventions"] == vca.CONVENTIONS
    # UTC like ion's own dateAdded, with the local time beside it
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", report["generated"])
    assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d[+-]\d{4}",
                        report["generated_local"])
    assert report["parameters"] == {
        "radius_m": 30.0, "max_km": 2.0, "footprint_margin_m": 5.0,
        "above_top_m": 10.0, "flight_logs": ["flight_log_T_2L_UTM.txt"]}
    assert "changes" not in report
    rows = {r["asset_id"]: r for r in report["assets"]}
    assert sorted(rows) == [21, 22, 23, 24, 25]

    assert [rows[21][key] for key in VERDICTS] == ["skipped"] * 4
    assert rows[21]["bytes"] == 4620000000        # source size is recorded too
    assert "description" not in rows[21]
    assert rows[21]["tileset_asset_id"] == 22

    assert rows[22]["description"] == "L run"
    assert rows[22]["date_added"] == "2026-09-27T03:11:00.000Z"
    assert rows[22]["verdict"] == "ok"
    assert rows[22]["tight_verdict"] == "MISSING-GEOID"
    assert rows[22]["best_verdict"] == "MISSING-GEOID"
    assert rows[22]["best_bracket_verdict"] == "MISSING-GEOID"
    assert (rows[22]["source_asset_id"], rows[22]["source_bytes"]) == (21, 4620000000)

    assert rows[23]["date_added"] == "2026-10-01T06:00:00.000Z"
    assert rows[23]["bytes"] == 555
    assert rows[23]["has_tight_box"] is False
    assert rows[23]["tight_verdict"] == "no-tight-box"
    assert rows[23]["verdict"] == rows[23]["best_verdict"] == "MISSING-GEOID"
    assert rows[23]["best_geometry"] == "root.boundingVolume.box"
    assert rows[23]["source_asset_id"] is None

    assert rows[24]["verdict"] == "skipped"
    assert rows[24]["why"] == "3DTILES/IN_PROGRESS"

    assert [rows[25][key] for key in VERDICTS] == ["unreadable"] * 4
    assert rows[25]["why"] == "RuntimeError: endpoint refused Bearer <redacted>"

    assert report["counts"] == {"skipped": 2, "ok": 1, "MISSING-GEOID": 1,
                                "unreadable": 1}
    assert report["tight_counts"] == {"skipped": 2, "MISSING-GEOID": 1,
                                      "no-tight-box": 1, "unreadable": 1}
    # the mesh AND the cloud are counted, each on its best box
    assert report["best_counts"] == {"skipped": 2, "MISSING-GEOID": 2,
                                     "unreadable": 1}
    assert report["bracket_counts"] == {"skipped": 2, "MISSING-GEOID": 2,
                                        "unreadable": 1}
    for label in ("root box ", "tight box", "best box ", "bracket  "):
        assert "\n" + label in printed
    assert "MISSING-GEOID (tight)" in printed and "MISSING-GEOID (root)" in printed


def test_the_console_table_never_cuts_a_name(tmp_path, monkeypatch, capsys):
    """'NA165 H2060 zone_1_c40_unscaled_L_dense' printed as '..._L_de' at 36
    characters: a mesh and its dense twin could not be told apart."""
    mesh, dense = ("NA165 H2060 zone_1_c40_unscaled_L",
                   "NA165 H2060 zone_1_c40_unscaled_L_dense")
    assert len(dense) > 36
    listing = [{"id": 1, "name": mesh, "type": "3DTILES", "status": "COMPLETE",
                "bytes": 1, "dateAdded": "2026-09-27T13:42:16.311Z"},
               {"id": 2, "name": dense, "type": "3DTILES", "status": "COMPLETE",
                "bytes": 1, "dateAdded": "2026-10-01T07:54:37.254Z"}]
    fake, _calls = fake_requests(listing, {}, {1: mesh_tileset(),
                                               2: cloud_tileset()})
    _report, printed = run_main(tmp_path, monkeypatch, capsys, fake)
    lines = printed.splitlines()
    assert any(re.search(re.escape(mesh) + r"\s", ln) for ln in lines)
    assert any(dense in ln for ln in lines)
    header = next(ln for ln in lines if ln.startswith("asset "))
    row = next(ln for ln in lines if dense in ln)
    assert header.index("verdict") == row.index("MISSING-GEOID")   # still aligned


def test_an_http_error_on_the_tileset_get_is_unreadable_not_a_fault(
        tmp_path, monkeypatch, capsys):
    """An error status whose body is JSON used to be decoded as a tileset
    and reported "FAULT, no root.transform"."""
    listing = [{"id": 7, "name": "expired", "type": "3DTILES",
                "status": "COMPLETE", "bytes": 1,
                "dateAdded": "2026-09-27T00:00:00.000Z"}]
    fake, _calls = fake_requests(
        listing, {}, {}, http_errors={7: "404 Client Error: Not Found"})
    report, _printed = run_main(tmp_path, monkeypatch, capsys, fake)
    row = report["assets"][0]
    assert row["verdict"] == "unreadable"
    assert row["why"] == "RuntimeError: 404 Client Error: Not Found"
    assert "has_root_transform" not in row


def test_an_external_asset_is_named_and_its_key_is_never_quoted_or_followed(
        tmp_path, monkeypatch, capsys):
    """Asset 2275207, Google Photorealistic 3D Tiles: the endpoint has no
    url / accessToken of ion's own - the report said why = "'url'". Its
    body carries the third party's URL with a key in it."""
    listing = [{"id": 2275207, "name": "Google Photorealistic 3D Tiles",
                "type": "3DTILES", "status": "COMPLETE", "bytes": 0,
                "dateAdded": "2023-09-12T23:15:05.489Z"}]
    endpoint = {"type": "3DTILES", "externalType": "GOOGLE_PHOTOREALISTIC",
                "options": {"url": "https://tile.example/root.json?key="
                                   + THIRD_PARTY_KEY}}
    fake, calls = fake_requests(listing, {}, {}, endpoints={2275207: endpoint})
    report, _printed = run_main(tmp_path, monkeypatch, capsys, fake)
    row = report["assets"][0]
    assert row["verdict"] == "unreadable"
    assert row["why"] == ("external asset (externalType GOOGLE_PHOTOREALISTIC)"
                          ": ion hosts no tileset for it")
    assert not any("tile.example" in c[0] for c in calls)     # never fetched


def test_compare_is_written_and_printed(tmp_path, monkeypatch, capsys):
    previous = tmp_path / "previous.json"
    previous.write_text(json.dumps({"schema": 2, "generated": "2026-10-01 10:24:26", "assets": [
        {"asset_id": 22, "name": "c2", "type": "3DTILES", "status": "COMPLETE",
         "bytes": 912345678, "verdict": "ok", "tight_verdict": "ok"},
        {"asset_id": 99, "name": "zone_2_c13_L", "type": "3DTILES",
         "status": "COMPLETE", "bytes": 3, "verdict": "MISSING-GEOID",
         "date_added": "2026-09-27T11:47:36.276Z"}]}), encoding="utf-8")
    listing = [{"id": 22, "name": "c2", "type": "3DTILES", "status": "COMPLETE",
                "bytes": 912345678, "dateAdded": "2026-09-27T03:11:00.000Z"},
               {"id": 23, "name": "c2 dense", "type": "3DTILES",
                "status": "COMPLETE", "bytes": 555,
                "dateAdded": "2026-10-01T06:00:00.000Z"}]
    fake, _calls = fake_requests(listing, {}, {22: mesh_tileset(),
                                               23: cloud_tileset()})
    report, printed = run_main(tmp_path, monkeypatch, capsys, fake,
                               extra=["--compare", str(previous)])
    changes = report["changes"]
    assert changes["against"] == "previous.json"
    assert [r["asset_id"] for r in changes["gone"]] == [99]
    assert [r["asset_id"] for r in changes["new"]] == [23]
    assert changes["changed"] == [{
        "asset_id": 22, "name": "c2", "was": {"tight_verdict": "ok"},
        "now": {"tight_verdict": "MISSING-GEOID"}}]
    assert ("against the report of 2026-10-01 10:24:26: 2 -> 2 assets, "
            "1 gone, 1 new, 1 changed") in printed
    assert re.search(r"gone\s+99\s.*zone_2_c13_L", printed)
    assert re.search(r"new\s+23\s.*c2 dense", printed)
    assert re.search(r"changed 22\s+c2: tight_verdict 'ok' -> 'MISSING-GEOID'",
                     printed)


class NoNetwork:
    """A ``requests`` that must not be reached."""
    def Session(self):
        raise AssertionError("a request was about to be made")


def test_what_is_wrong_locally_stops_the_run_before_any_request(
        tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "requests", NoNetwork())
    monkeypatch.setattr(vca, "geoid_lookup", lambda: geoid_stub)
    monkeypatch.setenv("CESIUM_ION_TOKEN", SECRET)
    log = nav(tmp_path)[0]["log"]

    not_a_report = tmp_path / "notes.json"
    not_a_report.write_text("[1, 2]", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["v", "--flight-log", log,
                                      "--compare", str(not_a_report)])
    with pytest.raises(SystemExit, match="not an audit report"):
        vca.main()

    empty = tmp_path / "flight_log_E_2L_UTM.txt"
    empty.write_text("Name;X (East);Y (North);Alt;XA;YA;AA\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["v", "--flight-log", str(empty)])
    with pytest.raises(SystemExit, match="no nav rows"):
        vca.main()


# ------------------------ what the second review's mutants walked through

def test_extent_m_stays_the_root_cube_on_a_tileset_with_a_tight_box(tmp_path):
    """The unprefixed ``extent_m`` and ``radius_m`` are the ROOT cell's on
    every row, tight box or not - that is what keeps a report comparable
    with the 2026-09-30 one. Taking them from the tight box passed the
    suite (review mutant V17)."""
    rec = audit(mesh_tileset(), tmp_path)
    assert rec["has_tight_box"] is True
    assert rec["extent_m"] == [46.0, 46.0, 46.0]
    assert rec["radius_m"] == pytest.approx(math.sqrt(3) * 23.0)
    assert rec["tight_extent_m"] == [10.0, 46.0, 4.0]
    assert rec["extent_m"] != rec["tight_extent_m"]


def lawn(tmp_path, name, east, north, alt, extra=()):
    """A 9 x 9 lawn of cameras about (east, north), plus ``extra`` rows."""
    from pyproj import Transformer
    rows = [(east + 5.0 * i, north + 5.0 * j, alt)
            for i in range(-4, 5) for j in range(-4, 5)] + list(extra)
    lines = ["Name;X (East);Y (North);Alt;XA;YA;AA"]
    lines += ["f%d.jpg;%.3f;%.3f;%.3f;10;10;1" % ((k,) + row)
              for k, row in enumerate(rows)]
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    crs = vca.utm_epsg(str(path))
    return {"log": str(path), "crs": crs, "rows": vca.load_nav(str(path)),
            "fwd": Transformer.from_crs("EPSG:4326", crs, always_xy=True)}


@pytest.mark.parametrize("far_first", [True, False])
def test_the_nearest_flight_log_wins_wherever_it_is_listed(tmp_path,
                                                           far_first):
    """Two dives in one zone, 1.5 km apart, inside --max-km of each other:
    the asset belongs to the one whose track passes over it, not to the
    first one given. With one log in every test, "the first" passed
    (review mutant V12)."""
    near = lawn(tmp_path, "flight_log_NEAR_2L_UTM.txt", SITE_EAST, SITE_NORTH,
                NAV_ALT)
    far = lawn(tmp_path, "flight_log_FAR_2L_UTM.txt", SITE_EAST + 1500.0,
               SITE_NORTH, -300.0)
    navs = [far, near] if far_first else [near, far]
    rec = vca.audit_tileset({}, mesh_tileset(), navs, geoid_stub, to_geo(),
                            30.0, 2.0)
    for prefix in ("", "tight_", "best_"):
        assert rec[prefix + "dive_log"] == "flight_log_NEAR_2L_UTM.txt"
        assert rec[prefix + "distance_to_track_m"] < 1.0
        assert rec[prefix + "nav_alt_median_m"] == NAV_ALT
    assert rec["tight_verdict"] == "MISSING-GEOID"

    # ... and the far dive alone is still a match, 1.5 km off its track,
    # so it was a real candidate and not one --max-km had already excluded
    alone = vca.audit_tileset({}, mesh_tileset(), [far], geoid_stub, to_geo(),
                              30.0, 2.0)
    assert alone["dive_log"] == "flight_log_FAR_2L_UTM.txt"
    assert alone["verdict"] == "FAULT"
    assert 1400.0 < alone["distance_to_track_m"] < 1500.0


def test_the_radius_is_the_radius(tmp_path):
    """A camera 29 m from the centre counts and one 31 m away does not:
    not twice the radius (review mutant V7), not half of it. The lawn alone
    could not tell - its farthest camera is 28.3 m out."""
    extra = [(SITE_EAST + 29.0, SITE_NORTH, -640.0),
             (SITE_EAST + 31.0, SITE_NORTH, -700.0),
             (SITE_EAST, SITE_NORTH - 58.0, -710.0)]
    navs = [lawn(tmp_path, "flight_log_R_2L_UTM.txt", SITE_EAST, SITE_NORTH,
                 NAV_ALT, extra)]
    rec = vca.audit_tileset({}, cloud_tileset(), navs, geoid_stub, to_geo(),
                            30.0, 2.0)
    assert rec["nav_rows_in_radius"] == 82            # the lawn, and 29 m
    assert rec["nav_alt_max_m"] == -640.0             # 29 m is inside
    assert rec["nav_alt_min_m"] == NAV_ALT            # 31 m and 58 m are not
    assert rec["nav_alt_median_m"] == NAV_ALT

    wide = vca.audit_tileset({}, cloud_tileset(), navs, geoid_stub, to_geo(),
                             32.0, 2.0)
    assert wide["nav_rows_in_radius"] == 83 and wide["nav_alt_min_m"] == -700.0
    narrow = vca.audit_tileset({}, cloud_tileset(), navs, geoid_stub,
                               to_geo(), 12.0, 2.0)
    # 5 m lawn: the cameras within 12 m of the centre are those with
    # i^2 + j^2 <= 5 - twenty-one of them
    assert narrow["nav_rows_in_radius"] == 21


def test_the_geoid_is_asked_at_lon_lat_in_that_order(tmp_path):
    """At this site lon is -169 and lat -14; swapped, EGM2008 would be read
    at latitude -169, which PROJ answers with inf or with another ocean's
    N. A stub that ignored its arguments could not tell (review mutant
    V14)."""
    asked = []

    def recording(lon, lat):
        asked.append((lon, lat))
        return STUB_N

    rec = vca.audit_tileset({}, mesh_tileset(), nav(tmp_path), recording,
                            to_geo(), 30.0, 2.0)
    assert len(asked) == 2                     # the root centre, the tight one
    for lon, lat in asked:
        assert lon == pytest.approx(SITE_LON, abs=1e-6)
        assert lat == pytest.approx(SITE_LAT, abs=1e-6)
    assert asked[0] == (rec["lon"], rec["lat"])
    assert asked[1] == (rec["tight_lon"], rec["tight_lat"])


def test_the_geoid_transform_refuses_a_ballpark(monkeypatch):
    """Without the grid PROJ offers a "ballpark" vertical transformation
    that returns Z unchanged: N = 0, every asset "ok". The transformer is
    EGM2008 -> WGS84 3D, lon / lat order, and built to REFUSE that (review
    mutant V21: allow_ballpark=True passed)."""
    import pyproj
    built = []

    class Grid:
        def transform(self, lon, lat, z):
            return lon, lat, STUB_N

    def from_crs(*args, **kwargs):
        built.append((args, kwargs))
        return Grid()

    monkeypatch.setattr(pyproj.Transformer, "from_crs", staticmethod(from_crs))
    assert vca.geoid_lookup()(SITE_LON, SITE_LAT) == STUB_N
    ((args, kwargs),) = built
    assert args == ("EPSG:9518", "EPSG:4979")
    assert kwargs == {"always_xy": True, "allow_ballpark": False}


class PagedSession:
    """An account of ``total`` assets, served a page at a time."""

    def __init__(self, total):
        self.total = total
        self.pages = []

    def get(self, url, headers=None, params=None, timeout=None):
        assert url == vca.API + "/v1/assets"
        assert headers == {"Authorization": "Bearer " + SECRET}
        assert params["limit"] == 100
        self.pages.append(params["page"])
        first = (params["page"] - 1) * 100
        items = [{"id": i} for i in range(first, min(first + 100, self.total))]
        return FakeResponse({"items": items})


@pytest.mark.parametrize("total, pages", [
    (0, [1]), (99, [1]), (100, [1, 2]), (101, [1, 2]), (250, [1, 2, 3]),
])
def test_the_listing_is_read_past_its_first_page(total, pages):
    """The account holds about 420 assets; ion serves 100 a page. Reading
    page one only passed every test (review mutant V20)."""
    session = PagedSession(total)
    items = vca.list_assets(session, SECRET)
    assert [a["id"] for a in items] == list(range(total))
    assert session.pages == pages


def test_rows_come_out_in_asset_id_order(tmp_path):
    """ion lists newest first; the report is in id order whatever the
    listing's (review mutant V23)."""
    assets = [{"id": i, "name": "a%d" % i, "type": "IMAGERY",
               "status": "COMPLETE"} for i in (30, 4, 17)]
    rows = vca.audit_assets(assets, None, nav(tmp_path), geoid_stub, to_geo(),
                            30.0, 2.0)
    assert [r["asset_id"] for r in rows] == [4, 17, 30]


# ----------------------------- nothing local may cost the audit its report

BAD_COMPARE = {
    "rows that are numbers": {"assets": [1, 2]},
    "assets is an object": {"assets": {"a": 1}},
    "an asset_id that is a list": {"assets": [{"asset_id": [1]}]},
    "an asset_id that is an object": {"assets": [{"asset_id": 7},
                                                 {"asset_id": {"x": 1}}]},
    "assets is null": {"assets": None},
}


@pytest.mark.parametrize("case", sorted(BAD_COMPARE))
def test_a_malformed_compare_file_is_refused_before_any_request(
        case, tmp_path, monkeypatch):
    """Each of these passed the old check (a dict with an "assets" key),
    then crashed the comparison after 400 GETs and BEFORE the report was
    written - about a minute of audit, lost."""
    monkeypatch.setitem(sys.modules, "requests", NoNetwork())
    monkeypatch.setattr(vca, "geoid_lookup", lambda: geoid_stub)
    monkeypatch.setenv("CESIUM_ION_TOKEN", SECRET)
    previous = tmp_path / "previous.json"
    previous.write_text(json.dumps(BAD_COMPARE[case]), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "v", "--flight-log", nav(tmp_path)[0]["log"],
        "--compare", str(previous), "--out", str(tmp_path / "audit.json")])
    with pytest.raises(SystemExit, match="is not an audit report: "):
        vca.main()
    assert not (tmp_path / "audit.json").exists()


def test_an_out_folder_that_is_not_there_is_refused_before_any_request(
        tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "requests", NoNetwork())
    monkeypatch.setattr(vca, "geoid_lookup", lambda: geoid_stub)
    monkeypatch.setenv("CESIUM_ION_TOKEN", SECRET)
    log = nav(tmp_path)[0]["log"]
    monkeypatch.setattr(sys, "argv", [
        "v", "--flight-log", log,
        "--out", str(tmp_path / "no_such_folder" / "audit.json")])
    with pytest.raises(SystemExit, match="--out: the folder .* does not exist"):
        vca.main()
    monkeypatch.setattr(sys, "argv", ["v", "--flight-log", log,
                                      "--out", str(tmp_path)])
    with pytest.raises(SystemExit, match="is a folder, not a file"):
        vca.main()


COMPARE_LISTING = [{"id": 22, "name": "c2", "type": "3DTILES",
                    "status": "COMPLETE", "bytes": 5,
                    "dateAdded": "2026-09-27T03:11:00.000Z"}]


def _previous(tmp_path):
    previous = tmp_path / "previous.json"
    previous.write_text(json.dumps({"schema": 3, "assets": [
        {"asset_id": 22, "name": "c2", "type": "3DTILES",
         "status": "COMPLETE", "bytes": 5, "tight_verdict": "ok"}]}),
        encoding="utf-8")
    return previous


def test_the_report_is_on_disk_before_the_comparison_is_printed(
        tmp_path, monkeypatch, capsys):
    """The comparison used to be computed and printed first, so anything
    wrong with it cost the report. Here printing it blows up: the report,
    with its ``changes`` block, is already written and the run ends 0."""
    report_was_written = []

    def explode(changes):
        report_was_written.append((tmp_path / "audit.json").exists())
        raise RuntimeError("console gone")

    monkeypatch.setattr(vca, "print_changes", explode)
    fake, _calls = fake_requests(COMPARE_LISTING, {}, {22: mesh_tileset()})
    report, printed = run_main(tmp_path, monkeypatch, capsys, fake,
                               extra=["--compare", str(_previous(tmp_path))])
    # printed once, and only after the file existed
    assert report_was_written == [True]
    assert report["changes"]["changed"][0]["asset_id"] == 22
    assert ("the comparison could not be printed (RuntimeError: console "
            "gone)") in printed
    assert printed.index("report ->") < printed.index("could not be printed")


def test_a_comparison_that_fails_is_recorded_and_the_audit_is_kept(
        tmp_path, monkeypatch, capsys):
    def explode(previous, rows):
        raise TypeError("unhashable type: 'list' near Bearer " + SECRET)

    monkeypatch.setattr(vca, "compare_reports", explode)
    fake, _calls = fake_requests(COMPARE_LISTING, {}, {22: mesh_tileset()})
    report, printed = run_main(tmp_path, monkeypatch, capsys, fake,
                               extra=["--compare", str(_previous(tmp_path))])
    assert "changes" not in report
    assert report["changes_error"] == (
        "TypeError: unhashable type: 'list' near Bearer <redacted>")
    assert report["assets"][0]["tight_verdict"] == "MISSING-GEOID"
    assert "the comparison with previous.json failed" in printed


def test_the_endpoints_own_token_is_scrubbed_too(tmp_path, monkeypatch,
                                                 capsys):
    """Only the account token and JWT-shaped strings were removed. The
    endpoint's token here is neither, and the tileset GET fails with it in
    the message - it reached ``why`` in the report."""
    assert not vca._JWT.search(ASSET_TOKEN)
    listing = [{"id": 9, "name": "refused", "type": "3DTILES",
                "status": "COMPLETE", "bytes": 1,
                "dateAdded": "2026-10-01T07:01:00.000Z"}]
    fake, calls = fake_requests(listing, {}, {}, tileset_refused={9})
    report, _printed = run_main(tmp_path, monkeypatch, capsys, fake)
    row = report["assets"][0]
    assert row["verdict"] == "unreadable"
    assert row["why"] == ("RuntimeError: tileset host refused Bearer "
                          "<redacted> (account Bearer <redacted>)")
    # ... and the token did go where it belongs
    assert calls[-1][1] == {"Authorization": "Bearer " + ASSET_TOKEN}


def _strict(text):
    """json.loads that refuses the NaN / Infinity tokens Python tolerates."""
    def refuse(token):
        raise AssertionError("%s is not JSON" % token)
    return json.loads(text, parse_constant=refuse)


NON_FINITE = {
    "a NaN in the transform": lambda root: root["transform"].__setitem__(
        12, float("nan")),
    "an infinite transform": lambda root: root["transform"].__setitem__(
        0, float("inf")),
    "a root box that overflows": lambda root: root["boundingVolume"].update(
        box=[0.0, 0.0, 0.0] + [1e300] * 9),
    "a root box centre of NaN": lambda root: root["boundingVolume"].update(
        box=[float("nan")] + CUBE[1:]),
    "a tight box that overflows": lambda root: root["metadata"][
        "properties"].update(tightBoundingBox=[0.0, 0.0, 0.0] + [1e300] * 9),
}


@pytest.mark.filterwarnings("ignore:overflow encountered")
@pytest.mark.parametrize("case", sorted(NON_FINITE))
def test_a_non_finite_centre_or_extent_is_unreadable_and_the_report_is_json(
        case, tmp_path, monkeypatch, capsys):
    """A degenerate transform or an overflowing box used to become a row of
    NaN heights and "FAULT" - and bare NaN / Infinity tokens in the report,
    which a strict JSON parser rejects whole."""
    with pytest.raises(vca.Unreadable, match="not finite"):
        vca.decode_tileset(_spoil(NON_FINITE[case]))

    listing = [{"id": 1, "name": "bad", "type": "3DTILES",
                "status": "COMPLETE", "bytes": 1,
                "dateAdded": "2026-10-01T07:01:00.000Z"},
               {"id": 2, "name": "good", "type": "3DTILES",
                "status": "COMPLETE", "bytes": 1,
                "dateAdded": "2026-10-01T07:02:00.000Z"}]
    fake, _calls = fake_requests(
        listing, {}, {1: _spoil(NON_FINITE[case]), 2: mesh_tileset()})
    report, _printed = run_main(tmp_path, monkeypatch, capsys, fake)
    bad, good = report["assets"]
    assert [bad[key] for key in VERDICTS] == ["unreadable"] * 4
    assert bad["why"].endswith("is not finite")
    assert "lon" not in bad and "extent_m" not in bad
    assert good["tight_verdict"] == "MISSING-GEOID"
    assert "non_finite_values_nulled" not in report
    text = (tmp_path / "audit.json").read_text(encoding="utf-8")
    assert _strict(text) == report
    assert not re.search(r"\bNaN\b|Infinity", text)


def test_a_centre_proj_cannot_convert_is_unreadable_not_a_row_of_inf(tmp_path):
    """PROJ answers a point it cannot convert with inf, not an exception."""
    class Lost:
        def transform(self, x, y, z):
            return float("inf"), float("inf"), float("inf")

    assets = [{"id": 1, "name": "lost", "type": "3DTILES",
               "status": "COMPLETE"}]
    (row,) = vca.audit_assets(assets, lambda i: cloud_tileset(), nav(tmp_path),
                              geoid_stub, Lost(), 30.0, 2.0)
    assert [row[key] for key in VERDICTS] == ["unreadable"] * 4
    assert row["why"] == ("the root box centre does not convert to lon / lat "
                          "/ height")
    assert "lon" not in row


def test_the_report_writer_never_emits_a_non_finite_token(tmp_path):
    """The second net: whatever non-finite value reaches the writer some
    other way is written as null and counted - the audit is not thrown
    away, and the file is still JSON."""
    path = tmp_path / "r.json"
    report = {"schema": 3, "assets": [
        {"asset_id": 1, "lon": float("nan"), "extent_m": [1.0, float("inf")]},
        {"asset_id": 2, "lon": -169.0, "nested": {"h": float("-inf")}}]}
    assert vca.write_report(report, str(path)) == 3
    written = _strict(path.read_text(encoding="utf-8"))
    assert written["non_finite_values_nulled"] == 3
    assert written["assets"][0] == {"asset_id": 1, "lon": None,
                                    "extent_m": [1.0, None]}
    assert written["assets"][1] == {"asset_id": 2, "lon": -169.0,
                                    "nested": {"h": None}}

    clean = {"schema": 3, "assets": [{"asset_id": 2, "lon": -169.0}]}
    assert vca.write_report(clean, str(path)) == 0
    assert _strict(path.read_text(encoding="utf-8")) == clean
