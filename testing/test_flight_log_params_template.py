"""Frame-aware FlightLogParams template selection (run2 blocker fix,
2026-08-08).

The align path used to hardcode the UTM template, which made every
local-frame campaign fail ensure_frame_match before a single zone could
align. The rule under test mirrors the frame guard exactly, so template
selection and enforcement can never disagree.
"""
import os
import sys

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
