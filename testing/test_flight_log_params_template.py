"""Frame-aware FlightLogParams template selection (run2 blocker fix,
2026-08-08).

The align path used to hardcode the UTM template, which made every
local-frame campaign fail ensure_frame_match before a single zone could
align. The rule under test mirrors the frame guard exactly, so template
selection and enforcement can never disagree.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.realityscan_interface.realityscan_interface import (
    flight_log_params_template)

MD = os.path.join("some", "metadata")


def test_untagged_log_selects_local_template():
    # ON2026-style local:1 campaign: no zone tag in the filename
    assert flight_log_params_template(MD, r"M:\x\flight_log_UTM.txt") \
        == os.path.join(MD, "FlightLogParamsLocal.xml")
    assert flight_log_params_template(MD, "flight_log_run2.txt") \
        == os.path.join(MD, "FlightLogParamsLocal.xml")


def test_zone_tagged_log_selects_utm_template():
    assert flight_log_params_template(MD, r"F:\x\flight_log_53N_UTM.txt") \
        == os.path.join(MD, "FlightLogParams.xml")
    assert flight_log_params_template(MD, "flight_log_NA167_H2075_57L_UTM.txt") \
        == os.path.join(MD, "FlightLogParams.xml")


def test_explicit_template_wins_over_frame_derivation():
    explicit = r"M:\campaign\MyParams.xml"
    assert flight_log_params_template(MD, "flight_log_53N_UTM.txt", explicit) \
        == explicit
    assert flight_log_params_template(MD, "flight_log_run2.txt", explicit) \
        == explicit


def test_no_log_defaults_to_utm_template_for_compatibility():
    assert flight_log_params_template(MD, None) \
        == os.path.join(MD, "FlightLogParams.xml")
    assert flight_log_params_template(MD, "") \
        == os.path.join(MD, "FlightLogParams.xml")


# ---------------------------------------------------------------------------
# ifKGrp - the flight-log import's calibration grouping mode
# ---------------------------------------------------------------------------
# MEASURED 2026-09-08 (_agent/probe_ifkgrp, 120 contiguous NA165/H2060 zone_2
# frames, one variable per cell):
#
#     ifKGrp=0   91 cameras   91 ungrouped   58 distinct focals  23.12-24.14 mm
#     ifKGrp=1   95 cameras    0 ungrouped    1 distinct focal   25.09 mm flat
#     ifKGrp=2   93 cameras   93 ungrouped   55 distinct focals  29.50-30.42 mm
#
# Historical single-camera result: only 1 created a group in that input.
# The template shipped 2 for the life of this repo, and the
# import runs AFTER AlignZone.bat sets the prior groups, so it overrode them
# on every dive: free per-image focal length, therefore free scale, therefore
# unmergeable components. NA165/H2060's first pass is the receipt - 35 of 43
# components outside the 0.90-1.10 scale band.
#
# SUPERSEDED for mixed-camera production by the 2026-09-11 v02 matrix:
# native calibration-only XMP delivers distinct focal/calibration/lens groups;
# ifKGrp=0 preserves them while ifKGrp=1 collapses all four camera groups.
# Retain the older observation as scoped provenance, not a universal enum rule.

_REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
METADATA = os.path.join(_REPO, 'modules', 'realityscan_interface',
                        'RS_CLI', 'Metadata')


@pytest.mark.parametrize('name', ['FlightLogParams.xml',
                                  'FlightLogParamsLocal.xml'])
def test_ifkgrp_preserves_native_per_camera_groups(name):
    with open(os.path.join(METADATA, name), encoding='utf-8') as fh:
        text = fh.read()
    assert '<entry key="ifKGrp" value="0"/>' in text, (
        f'{name}: ifKGrp must be 0 for native calibration + CSV pose. '
        'Measured v02 2026-09-11: 1 collapses distinct camera groups; '
        '0 preserves the groups supplied by native XMP.')
    assert '<entry key="ifKGrp" value="1"/>' not in text
    assert '<entry key="ifKGrp" value="2"/>' not in text


@pytest.mark.parametrize('name', ['FlightLogParams.xml',
                                  'FlightLogParamsLocal.xml'])
def test_the_measurement_travels_with_the_value(name):
    """The value is undocumented and looks arbitrary; without the numbers
    beside it the next reader has no way to know 2 was measured to be wrong,
    and this is exactly the kind of line that gets 'tidied' back."""
    with open(os.path.join(METADATA, name), encoding='utf-8') as fh:
        text = fh.read()
    assert 'ifKGrp=1' in text and 'ifKGrp=2' in text, \
        f'{name}: the comparison table must stay beside the entry'
    assert 'CalibrationGroup' in text
