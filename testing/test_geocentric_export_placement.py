#!/usr/bin/env python3
"""A geocentric export must not be read as the project's projected CRS.

WHY THIS EXISTS. NA165/H2060's OBJ exports carried BOTH of these in one
sidecar:

    globalCoordinateSystemName="epsg:32702 - WGS 84 / UTM zone 2S"
    exportCoordinateSystemType="3"

and vertices like (-6070883.4, -1174959.9, -1555436.0). The name is true
about the PROJECT; the vertices are ECEF. Reading the name as the vertex
frame put the publish anchor at lon 90.45, lat -38.49, depth -1,555,435 m -
the Indian Ocean, 1,555 km down - for a dive off American Samoa at 690 m.

Nothing about those numbers looks wrong until they are transformed, and the
sidecar is not lying: it is answering a different question from the one
being asked. Caught in a --dry-run, before 39 components were published.

The second half of the fix matters as much as the first. ECEF is not a
projected frame, so subtracting an ECEF anchor yields a geocentric offset
rather than East-North-Up: the mesh would land in roughly the right place
with the wrong ORIENTATION, which checking the position would never catch.
And a geocentric Z is already an ellipsoidal height, so the geoid
correction that a projected export needs must not fire here.

Run:  python -m pytest testing/test_geocentric_export_placement.py
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.cesium_placement import (  # noqa: E402
    PlacementError, RSInfo, _geocentric_to_projected,
)

# The real component, measured 2026-09-14. Centroid of zone_1_c40's OBJ.
ECEF_CENTROID = (-6070882.485, -1174959.182, -1555435.376)
# What it must come out as: American Samoa, at the dive's own seabed depth.
EXPECTED_LON, EXPECTED_LAT, EXPECTED_H = -169.046395, -14.210830, -690.0


def _info(cs_type, name='epsg:32702 - WGS 84 / UTM zone 2S'):
    from pathlib import Path
    return RSInfo(path=Path('zone_1_c40_0000000.obj.rsInfo'), crs_proj=None,
                  crs_name=name, crs_wkt=None, export_cs_type=cs_type,
                  transform=None)


def test_geocentric_type_wins_over_the_project_crs_name():
    """The incident, in one assertion."""
    assert _info('3').crs == 'EPSG:4978'


def test_the_project_crs_name_is_still_reachable():
    """It is not wrong, just not the vertex frame - and the conversion needs
    it to know where to put the mesh."""
    assert _info('3').epsg == 'EPSG:32702'


def test_a_projected_export_is_unaffected():
    """The pre-existing path must not change: only type 3 means geocentric."""
    assert _info('1').crs == 'EPSG:32702'
    assert _info(None).crs == 'EPSG:32702'


def test_conversion_lands_the_real_component_in_american_samoa():
    """End to end on the measured centroid, against an independent fact: the
    dive's seabed is at ~690 m and its nav envelope centres on
    (-169.0469, -14.2124). Read as UTM 2S the same numbers give lat 0 and a
    depth of -1,555 km."""
    from pyproj import Transformer
    out = _geocentric_to_projected([ECEF_CENTROID], 'EPSG:32702')
    east, north, up = out[0]
    lon, lat = Transformer.from_crs('EPSG:32702', 'EPSG:4326',
                                    always_xy=True).transform(east, north)
    assert lon == pytest.approx(EXPECTED_LON, abs=1e-4)
    assert lat == pytest.approx(EXPECTED_LAT, abs=1e-4)
    assert up == pytest.approx(EXPECTED_H, abs=1.0)


def test_conversion_preserves_metric_scale():
    """The whole point of converting rather than localising in ECEF. Two
    points a known distance apart must stay that distance apart, or the
    deliverable's metric scale - the thing the scale gate spent 32 refused
    components defending - is lost at the last step."""
    import numpy as np
    a = np.array(ECEF_CENTROID)
    # 10 m along ECEF X is 10 m on the ground too, to well within tolerance.
    b = a + np.array([10.0, 0.0, 0.0])
    out = _geocentric_to_projected([a, b], 'EPSG:32702')
    moved = float(np.linalg.norm(out[1] - out[0]))
    assert moved == pytest.approx(10.0, abs=0.01)


def test_non_finite_output_is_refused():
    """A NaN vertex must raise rather than publish.

    Scope, stated honestly because the first version of this test asserted
    more than the guard delivers: pyproj does NOT produce infinities for
    absurd-but-finite input. (1e30, 1e30, 1e30) converts to a perfectly
    finite easting/northing of (-2.84e6, 2.54e7) - garbage, but finite, and
    this check passes it through. The finite-check catches NaN propagation
    from a corrupt mesh, not nonsense magnitudes; the nav-envelope
    cross-check in plan_placement is what catches those.
    """
    with pytest.raises(PlacementError):
        _geocentric_to_projected([(float('nan'), 0.0, 0.0)], 'EPSG:32702')


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
