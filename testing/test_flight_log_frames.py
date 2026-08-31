"""Frame generalization of the flight-log params (two-frames hazard,
incident 2026-08-07: the shared FlightLogParams template carried ON2026's
local frame and silently poisoned a UTM 57L import - 3/32 cameras
registered with exit code 0). Covers UTM/local generation via
write_flight_log_params, the template-vs-frame mismatch guard in both
directions, and ensure_frame_match (the guard realityscan_interface.py
runs before every import). Offline - no RealityScan interaction."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from modules.flight_logs import (ensure_frame_match, params_template_frame,
                                 write_flight_log_params)

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
METADATA = os.path.join(REPO, 'modules', 'realityscan_interface',
                        'RS_CLI', 'Metadata')
UTM_TEMPLATE = os.path.join(METADATA, 'FlightLogParams.xml')
LOCAL_TEMPLATE = os.path.join(METADATA, 'FlightLogParamsLocal.xml')


def read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


class TestCommittedTemplates(unittest.TestCase):
    """Tripwire for the exact incident: 902fcf7 hand-promoted local-frame
    content into the shared template. If either committed template ever
    switches frames again, these fail before any import does."""

    def test_shared_template_declares_utm(self):
        self.assertEqual(params_template_frame(UTM_TEMPLATE), 'utm')

    def test_local_template_declares_local(self):
        self.assertEqual(params_template_frame(LOCAL_TEMPLATE),
                         'local_euclidean')


class TestUtmGeneration(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_flight_log_params(
                UTM_TEMPLATE, os.path.join(tmp, 'p53N.xml'), 53, 'N')
            content = read(out)
            self.assertIn('+proj=utm +zone=53 +datum=WGS84 +units=m +no_defs',
                          content)
            self.assertNotIn('+south', content)
            self.assertIn('epsg:32653 - WGS 84 / UTM zone 53N', content)
            self.assertEqual(params_template_frame(out), 'utm')
            # A generated file is itself a valid UTM template (round trip,
            # southern hemisphere this time).
            out2 = write_flight_log_params(
                out, os.path.join(tmp, 'p9L.xml'), 9, 'L')
            content2 = read(out2)
            self.assertIn('+proj=utm +zone=9 +south +datum=WGS84', content2)
            self.assertIn('epsg:32709 - WGS 84 / UTM zone 9S', content2)

    def test_utm_frame_requires_zone_and_band(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                write_flight_log_params(
                    UTM_TEMPLATE, os.path.join(tmp, 'x.xml'), frame='utm')

    def test_unknown_frame_value_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                write_flight_log_params(
                    UTM_TEMPLATE, os.path.join(tmp, 'x.xml'), 53, 'N',
                    frame='wgs84')


class TestLocalGeneration(unittest.TestCase):
    def test_local_pair_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_flight_log_params(
                LOCAL_TEMPLATE, os.path.join(tmp, 'local.xml'),
                frame='local_euclidean')
            content = read(out)
            self.assertIn('+proj=geocent +ellps=WGS84 +no_defs', content)
            self.assertIn('local:1 - Euclidean', content)
            self.assertEqual(params_template_frame(out), 'local_euclidean')

    def test_zone_and_band_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_flight_log_params(
                LOCAL_TEMPLATE, os.path.join(tmp, 'local.xml'), 53, 'N',
                frame='local_euclidean')
            content = read(out)
            self.assertNotIn('+proj=utm', content)
            self.assertIn('local:1 - Euclidean', content)


class TestTemplateMismatchGuard(unittest.TestCase):
    """write_flight_log_params refuses a template that declares the
    opposite frame from the one requested - both directions."""

    def test_utm_request_against_local_template_trips(self):
        # The incident direction: UTM 57L log, local template.
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as ctx:
                write_flight_log_params(
                    LOCAL_TEMPLATE, os.path.join(tmp, 'x.xml'), 57, 'L')
            self.assertIn('2026-08-07', str(ctx.exception))

    def test_local_request_against_utm_template_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as ctx:
                write_flight_log_params(
                    UTM_TEMPLATE, os.path.join(tmp, 'x.xml'),
                    frame='local_euclidean')
            self.assertIn('2026-08-07', str(ctx.exception))

    def test_matched_pairs_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_flight_log_params(
                UTM_TEMPLATE, os.path.join(tmp, 'utm.xml'), 57, 'L',
                frame='utm')
            write_flight_log_params(
                LOCAL_TEMPLATE, os.path.join(tmp, 'local.xml'),
                frame='local_euclidean')


class TestEnsureFrameMatch(unittest.TestCase):
    """The filename-vs-template guard realityscan_interface.py runs
    before deciding how to build the params file."""

    def test_tagged_log_against_local_template_trips(self):
        with self.assertRaises(ValueError) as ctx:
            ensure_frame_match('flight_log_57L_UTM.txt', LOCAL_TEMPLATE)
        self.assertIn('2026-08-07', str(ctx.exception))

    def test_untagged_log_against_utm_template_trips(self):
        with self.assertRaises(ValueError) as ctx:
            ensure_frame_match('flight_log_zones.txt', UTM_TEMPLATE)
        self.assertIn('2026-08-07', str(ctx.exception))

    def test_matched_pairs_pass(self):
        self.assertEqual(
            ensure_frame_match('flight_log_57L_UTM.txt', UTM_TEMPLATE),
            'utm')
        self.assertEqual(
            ensure_frame_match('flight_log_zones.txt', LOCAL_TEMPLATE),
            'local_euclidean')


if __name__ == '__main__':
    unittest.main()
