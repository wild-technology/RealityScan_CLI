"""The RealityScan orientation frame: pitch 0 = nadir, 90 = horizontal.

This conversion decides which way every camera in every solve is claimed to
point, and until 2026-08-31 it had **no test at all** - the two
implementations (`geoall.convert_to_rc_orientation` and the georeference
module's `_convert_to_rc_orientation`) were free to drift, and a
same-session claim that "we write pitch from horizontal, so Port is 90 deg
wrong" had to be refuted by argument rather than by a red test.

The convention is not a house choice, it is RealityScan's:
`-renderMeshFromCustomPositionYPR` documents a camera at `(0,0,150)` with
`yaw=pitch=roll=0` looking **down**, so **pitch 0 is nadir** on a scale where
90 is horizontal. [OFFICIAL: appbasics/allcommands; docs/rs-reference/13 6.4]

    rc_pitch = 90 + (vehicle_pitch - mount_down_tilt)

Read it as: start horizontal (90), tilt the camera down by its mount angle,
then add whatever the vehicle itself is doing.
"""
from __future__ import annotations

import logging
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import geoall  # noqa: E402
from modules.georeference.georeference_images import (  # noqa: E402
    ASSUMED_MOUNT_DEFAULTS, GeoreferenceImages, MOUNTS,
    NO_ASSUMED_MOUNT_FAMILIES)


def convert(heading=0.0, vehicle_pitch=0.0, roll=0.0, tilt=0.0, decl=0.0):
    return geoall.convert_to_rc_orientation(heading, vehicle_pitch, roll,
                                            tilt, decl)


# --------------------------------------------------------------------------
# the convention itself
# --------------------------------------------------------------------------

@pytest.mark.parametrize('tilt,expected,what', [
    (0.0, 90.0, 'a camera looking straight along the vehicle axis is HORIZONTAL'),
    (90.0, 0.0, 'a camera tilted 90 deg down is NADIR - pitch 0'),
    (10.0, 80.0, 'the house convention: 10 deg down from horizontal'),
    (45.0, 45.0, 'Cinema under WCA names'),
    (30.0, 60.0, 'Zeuss'),
    (70.0, 20.0, 'legacy camupper'),
])
def test_mount_tilt_maps_onto_the_nadir_scale(tilt, expected, what):
    _yaw, pitch, _roll = convert(vehicle_pitch=0.0, tilt=tilt)
    assert pitch == pytest.approx(expected), what


def test_pitch_is_referenced_to_nadir_not_to_horizontal():
    """The refuted claim, now pinned: if this were measured FROM horizontal,
    a nadir camera would come out at 90 rather than 0."""
    _y, nadir, _r = convert(tilt=90.0)
    _y, horizontal, _r = convert(tilt=0.0)
    assert nadir == pytest.approx(0.0)
    assert horizontal == pytest.approx(90.0)
    assert nadir < horizontal, 'the scale is inverted'


def test_vehicle_attitude_composes_with_the_mount():
    """'Inline with the vehicle's rotation': the mount is an offset FROM the
    vehicle's own pitch, not a replacement for it."""
    # Vehicle nose-up 5 deg lifts the camera 5 deg on the nadir scale.
    assert convert(vehicle_pitch=5.0, tilt=10.0)[1] == pytest.approx(85.0)
    # Vehicle nose-down 5 deg pushes it toward nadir.
    assert convert(vehicle_pitch=-5.0, tilt=10.0)[1] == pytest.approx(75.0)


def test_yaw_is_true_heading_and_wraps():
    assert convert(heading=350.0, decl=20.0)[0] == pytest.approx(10.0)
    assert convert(heading=10.0, decl=-20.0)[0] == pytest.approx(350.0)
    assert 0.0 <= convert(heading=359.9, decl=0.5)[0] < 360.0


def test_roll_passes_through_untouched():
    assert convert(roll=-3.25)[2] == pytest.approx(-3.25)


# --------------------------------------------------------------------------
# absent inputs must produce no prior, never a zero
# --------------------------------------------------------------------------

def test_missing_vehicle_pitch_yields_no_pitch_prior():
    assert geoall.convert_to_rc_orientation(10.0, None, 0.0, 10.0, 0.0)[1] is None


def test_missing_mount_tilt_yields_no_pitch_prior():
    """`convert_to_rc_orientation` is the last line of defence: whatever the
    caller decided about assumed mounts, a None tilt here must not become 0."""
    assert geoall.convert_to_rc_orientation(10.0, 0.0, 0.0, None, 0.0)[1] is None


def test_missing_heading_yields_no_yaw():
    assert geoall.convert_to_rc_orientation(None, 0.0, 0.0, 10.0, 0.0)[0] is None


# --------------------------------------------------------------------------
# the two implementations must not drift
# --------------------------------------------------------------------------

@pytest.mark.parametrize('heading,vp,roll,tilt,decl', [
    (0.0, 0.0, 0.0, 10.0, 0.0),
    (137.5, 3.25, -2.0, 45.0, 11.5),
    (359.0, -8.0, 15.0, 0.0, -4.0),
    (90.0, 0.0, 0.0, 90.0, 0.0),
])
def test_geoall_and_the_module_agree(heading, vp, roll, tilt, decl):
    module = GeoreferenceImages(logging.getLogger('quiet'))
    assert (module._convert_to_rc_orientation(heading, vp, roll, tilt, decl)
            == geoall.convert_to_rc_orientation(heading, vp, roll, tilt, decl))


# --------------------------------------------------------------------------
# the assumed mount
# --------------------------------------------------------------------------

def test_the_assumed_mount_lands_10_degrees_below_horizontal():
    """End to end: the house convention expressed in RealityScan's frame."""
    tilt = ASSUMED_MOUNT_DEFAULTS['pitch']
    assert convert(vehicle_pitch=0.0, tilt=tilt)[1] == pytest.approx(80.0)


def test_measured_mounts_are_unchanged_by_the_assumption():
    """Regression guard: adding the fallback must not have moved any mount
    that was actually measured."""
    assert MOUNTS['zeuss']['pitch'] == 30.0
    assert MOUNTS['legacy_camupper']['pitch'] == 70.0
    assert MOUNTS['legacy_cammid']['pitch'] == 20.0
    assert MOUNTS['legacy_camlower']['pitch'] == 10.0
    assert MOUNTS['wca_port']['pitch'] == 0.0
    assert MOUNTS['wca_cinema']['pitch'] == 45.0
    assert MOUNTS['wca_starboard'] is None
    for family in NO_ASSUMED_MOUNT_FAMILIES:
        assert MOUNTS[family] is None


def test_port_sits_at_the_documented_degeneracy_boundary():
    """Port's 0 deg mount puts it at ~90 deg on the nadir scale, within 2 deg
    of the yaw/roll singularity flagged in docs/rs-reference/13 6.4. Pinned
    so the hazard is visible rather than rediscovered."""
    pitch = convert(vehicle_pitch=-2.0, tilt=MOUNTS['wca_port']['pitch'])[1]
    assert abs(pitch - 90.0) < 5.0
