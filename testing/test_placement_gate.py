#!/usr/bin/env python3
"""The placement gate: the sidecar's reading, checked against the nav.

WHY THIS EXISTS. On 2026-09-14 publish_cesium believed an .rsInfo whose
globalCoordinateSystemName said UTM 2S while the vertices were ECEF, and put
NA165/H2060's anchor at lon 90.45, lat -38.49, depth -1,555,435 m. The fix
was verified on one 52-camera component; _agent/export/placement_check.py was
the gate that ran it on the dive, with this dive's numbers hard-coded (5 km
from the nav centre, depth -1200..-300 m). modules/placement_gate.py is that
gate made generic: both bounds come from the flight log.

Hermetic: a geocentric (exportCoordinateSystemType 3) fixture, so no geoid
grid is needed, built around zone_1_c40's real ECEF centroid - the same one
test_geocentric_export_placement.py pins.

Run:  python -m pytest testing/test_placement_gate.py
"""
from __future__ import annotations

import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO_ROOT)

np = pytest.importorskip('numpy')
pyproj = pytest.importorskip('pyproj')

from modules import placement_gate as pg  # noqa: E402

# zone_1_c40's OBJ centroid, measured 2026-09-14 (American Samoa, ~-690 m).
ECEF_CENTROID = (-6070882.485, -1174959.182, -1555435.376)

RSINFO = ('<Model globalCoordinateSystemName="epsg:32702 - WGS 84 / UTM zone 2S" '
          'exportCoordinateSystemType="3" '
          'transformToModel="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1">\n'
          '  <Header magic="5786959" version="2"/>\n</Model>\n')


def _centroid_utm():
    t = pyproj.Transformer.from_crs('EPSG:4978', 'EPSG:32702', always_xy=True)
    return t.transform(*ECEF_CENTROID)


def _component(tmp_path, shift_ecef=(0.0, 0.0, 0.0), spread=1.0):
    obj_dir = tmp_path / 'zone_1_c40_L' / 'obj'
    obj_dir.mkdir(parents=True)
    c = np.array(ECEF_CENTROID) + np.array(shift_ecef)
    pts = [c + np.array(d) * spread for d in
           ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), (-1, -1, -1))]
    (obj_dir / 'zone_1_c40_L_0000000.obj').write_text(
        ''.join('v %.4f %.4f %.4f\n' % tuple(p) for p in pts), encoding='utf-8')
    (obj_dir / 'zone_1_c40_L_0000000.obj.rsInfo').write_text(RSINFO, encoding='utf-8')
    return obj_dir


def _flight_log(tmp_path, de=0.0, dn=0.0):
    e, n, _ = _centroid_utm()
    rows = ['Name;X (East);Y (North);Alt']
    for i, (x, y, z) in enumerate(((e - 100 + de, n - 200 + dn, -689.0),
                                   (e + 100 + de, n + 200 + dn, -643.0),
                                   (0.0, 0.0, 0.0))):       # missing-nav marker
        rows.append('f%d.jpg;%.3f;%.3f;%.3f' % (i, x, y, z))
    path = tmp_path / 'flight_log_2L_UTM.txt'
    path.write_text('\n'.join(rows) + '\n', encoding='utf-8')
    return path


def test_the_real_component_shape_passes(tmp_path):
    obj_dir = _component(tmp_path)
    log = _flight_log(tmp_path)
    out = tmp_path / 'verdict.json'
    assert pg.main(['--dir', str(obj_dir), '--flight-log', str(log),
                    '--json', str(out)]) == 0
    verdict = json.loads(out.read_text(encoding='utf-8'))
    assert verdict['pass'] and verdict['measured']['outside_envelope_m'] == 0.0
    assert verdict['measured']['z_is_ellipsoidal']


def test_a_mesh_far_from_the_dive_fails(tmp_path):
    obj_dir = _component(tmp_path)
    log = _flight_log(tmp_path, de=10_000.0)       # nav 10 km east
    assert pg.main(['--dir', str(obj_dir), '--flight-log', str(log)]) == 1


def test_the_bounds_come_from_the_nav_not_from_this_dive():
    """The dive-local original hard-coded -1200..-300 m. A 3,000 m dive must
    pass on its own nav, and a 690 m anchor must fail against it."""
    nav = {'east': (0.0, 100.0), 'north': (0.0, 100.0), 'alt': (-3010.0, -2990.0)}
    plan = {'anchor_projected': [50.0, 50.0, -3000.0], 'extent_m': [5, 5, 1]}
    assert pg.check_plan(plan, nav)[1] == []
    plan['anchor_projected'][2] = -690.0
    assert any('depth band' in f for f in pg.check_plan(plan, nav)[1])


def test_the_incident_depth_is_refused():
    nav = {'east': (0.0, 100.0), 'north': (0.0, 100.0), 'alt': (-689.0, -643.0)}
    plan = {'anchor_projected': [50.0, 50.0, -1_555_435.0], 'extent_m': [1, 1, 1]}
    assert pg.check_plan(plan, nav)[1]


def test_inside_the_envelope_is_zero_outside_is_measured():
    nav = {'east': (0.0, 100.0), 'north': (0.0, 100.0), 'alt': (-1.0, 0.0)}
    assert pg.outside_envelope_m(50.0, 50.0, nav) == 0.0
    assert pg.outside_envelope_m(103.0, 104.0, nav) == pytest.approx(5.0)


def test_extent_check_is_off_by_default_and_catches_a_collapse():
    """NA165's delivered zone_2_c18 (70 cameras) spans 0.3 x 0.5 x 0.3 m and
    passes position and depth. The extent check exists for that; it is
    opt-in because a sound small component can be a metre across."""
    nav = {'east': (0.0, 100.0), 'north': (0.0, 100.0), 'alt': (-1.0, 0.0)}
    plan = {'anchor_projected': [50.0, 50.0, -0.5], 'extent_m': [0.3, 0.5, 0.3]}
    assert pg.check_plan(plan, nav)[1] == []
    assert pg.check_plan(plan, nav, min_extent_m=1.0)[1]


def test_no_obj_is_a_failure_not_a_pass(tmp_path):
    (tmp_path / 'obj').mkdir()
    log = _flight_log(tmp_path)
    assert pg.main(['--dir', str(tmp_path / 'obj'), '--flight-log', str(log)]) == 1


def test_the_gate_never_writes_beside_the_mesh(tmp_path):
    obj_dir = _component(tmp_path)
    before = sorted(p.name for p in obj_dir.iterdir())
    pg.main(['--dir', str(obj_dir), '--flight-log', str(_flight_log(tmp_path))])
    assert sorted(p.name for p in obj_dir.iterdir()) == before


# ------------------------------------------------ review 2026-09-27

def test_the_gate_leaves_proj_networking_as_it_found_it(tmp_path):
    """It compares anchor_projected and needs no geoid grid; switching PROJ
    networking on (process-wide) made later tests network-dependent and made
    an offline projected export 'FAIL: placement could not be computed'."""
    from pyproj import network
    was = network.is_network_enabled()
    try:
        network.set_network_enabled(False)
        assert pg.main(['--dir', str(_component(tmp_path)),
                        '--flight-log', str(_flight_log(tmp_path))]) == 0
        assert network.is_network_enabled() is False
    finally:
        network.set_network_enabled(was)


def test_min_extent_is_a_collapse_check_on_the_larger_horizontal_extent():
    """Fails only when the mesh is small in BOTH horizontal directions: a
    long thin component is sound."""
    nav = {'east': (0.0, 100.0), 'north': (0.0, 100.0), 'alt': (-1.0, 0.0)}
    thin = {'anchor_projected': [50.0, 50.0, -0.5], 'extent_m': [0.2, 10.0, 0.3]}
    assert pg.check_plan(thin, nav, min_extent_m=1.0)[1] == []
    small = {'anchor_projected': [50.0, 50.0, -0.5], 'extent_m': [0.9, 0.8, 5.0]}
    assert pg.check_plan(small, nav, min_extent_m=1.0)[1]


def test_a_mesh_that_cannot_be_placed_fails(tmp_path):
    obj_dir = _component(tmp_path)
    (obj_dir / 'zone_1_c40_L_0000000.obj.rsInfo').unlink()   # no frame record
    assert pg.main(['--dir', str(obj_dir),
                    '--flight-log', str(_flight_log(tmp_path))]) == 1


def test_bad_inputs_are_exit_2(tmp_path):
    obj_dir = _component(tmp_path)
    log = _flight_log(tmp_path)
    assert pg.main(['--dir', str(tmp_path / 'absent'), '--flight-log', str(log)]) == 2
    assert pg.main(['--dir', str(obj_dir),
                    '--flight-log', str(tmp_path / 'absent.txt')]) == 2
