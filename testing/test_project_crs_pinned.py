"""
The project/output CRS must be pinned, and pinned BEFORE the trajectory import.

RealityScan holds three CRS scopes (docs/rs-reference/06 3.2):

  project    -setProjectCoordinateSystem   measuring, display, accuracy reports
  output     -setOutputCoordinateSystem    MODEL/MESH EXPORT
  per-object CoordinateSystemFlightLog     only "the CRS the imported numbers are in"

This repo set only the third. RealityScan's Help says to set the project CRS
FIRST and then import; the reference file records that this repo never called
it and flagged the consequence as OPEN.

NA165/H2060 answered it. A project accumulates a LIST of coordinate systems
across cruises; the master carried three:

    index 1  epsg:32655  UTM 55N   <- what every exported .rsInfo declared
    index 2  epsg:32757  UTM 57S   <- NA173's, and what projectCoordinates selected
    index 3  epsg:32702  UTM 2S    <- the dive's actual frame, used only by the
                                      image priors (absCs="3")

So the declared CRS was not stale, it was ARBITRARY - whichever leftover sorted
first - which is worse than wrong because it looks authoritative. Reading it
literally puts the mesh ~16,000 km away.

Order is the part that rots silently: pinning AFTER the import still leaves the
import itself running against the wrong project CRS, and nothing complains.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.flight_logs import epsg_for_utm_zone

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'modules', 'realityscan_interface', 'RS_CLI', 'Scripts')


def _read(name):
    with open(os.path.join(SCRIPTS, name), encoding='utf-8', errors='replace') as fh:
        return fh.read()


def test_h2060_zone_maps_to_southern_epsg():
    # The dive that exposed this: UTM 2S, not 2N and not a leftover.
    # H2060's flight log is tagged 2L - L is the MGRS BAND, and bands C..M are
    # southern - so it resolves to 32702.
    assert epsg_for_utm_zone(2, 'L') == 32702


def test_band_S_is_NORTHERN_despite_looking_like_south():
    # A live trap in this codebase, because BOTH notations are in use:
    #   "2S"  hemisphere notation  -> zone 2 SOUTH  (ROVDataConcat writes this)
    #   "2S"  MGRS band notation   -> band S is NORTHERN (bands N..X are north)
    # The flight log is tagged with the BAND (2L), and epsg_for_utm_zone takes
    # a BAND. Passing the hemisphere letter 'S' here silently yields the
    # NORTHERN zone - the exact class of error that put a 55N label on a 2S
    # dive in the first place.
    assert epsg_for_utm_zone(2, 'S') == 32602      # band S -> NORTH
    assert epsg_for_utm_zone(2, 'L') == 32702      # band L -> SOUTH
    assert epsg_for_utm_zone(2, 'S') != epsg_for_utm_zone(2, 'L')


def test_northern_and_southern_do_not_collide():
    assert epsg_for_utm_zone(55, 'U') == 32655      # the leftover that was declared
    assert epsg_for_utm_zone(57, 'L') == 32757      # NA173's
    assert epsg_for_utm_zone(2, 'L') == 32702       # ours
    assert len({32655, 32757, 32702}) == 3


def test_alignzone_pins_both_scopes():
    s = _read('AlignZone.bat')
    assert '-setProjectCoordinateSystem %RS_PROJECT_CRS%' in s
    assert '-setOutputCoordinateSystem %RS_PROJECT_CRS%' in s


def test_alignzone_pins_BEFORE_importing_the_flight_log():
    # RealityScan's Help: set the project CRS first, THEN import. Pinning after
    # the import leaves the import running against the wrong project CRS, and
    # nothing reports it.
    s = _read('AlignZone.bat')
    pin = s.index('-setProjectCoordinateSystem')
    imp = s.index('-importFlightLog')
    assert pin < imp, 'project CRS must be pinned before -importFlightLog'


def test_pinning_is_guarded_so_an_unset_var_cannot_pass_an_empty_arg():
    # `-setProjectCoordinateSystem ""` would be a silent mis-set; both call
    # sites must be inside a defined-and-non-empty guard.
    for name in ('AlignZone.bat', 'ExportDeliverables.bat'):
        s = _read(name)
        for line in s.splitlines():
            if '-setProjectCoordinateSystem' in line or '-setOutputCoordinateSystem' in line:
                if line.strip().startswith('::'):
                    continue
                assert '%RS_PROJECT_CRS%' in line, name
        assert 'if defined RS_PROJECT_CRS' in s, name
        assert 'if not "%RS_PROJECT_CRS%" == ""' in s, name


def test_export_pins_the_output_scope():
    # The export is where the CRS is actually written into .rsInfo.
    s = _read('ExportDeliverables.bat')
    assert '-setOutputCoordinateSystem %RS_PROJECT_CRS%' in s
    pin = s.index('-setOutputCoordinateSystem')
    first_export = s.index('-exportModel')
    assert pin < first_export, 'output CRS must be pinned before any -exportModel'


def test_align_module_sets_the_env_var_from_the_flight_log_zone():
    src_path = os.path.join(os.path.dirname(SCRIPTS), '..', 'realityscan_interface.py')
    src_path = os.path.normpath(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'modules', 'realityscan_interface', 'realityscan_interface.py'))
    with open(src_path, encoding='utf-8') as fh:
        src = fh.read()
    assert "os.environ['RS_PROJECT_CRS']" in src
    # It must be derived from the log's OWN zone/band, never hardcoded.
    m = re.search(r"RS_PROJECT_CRS'\]\s*=\s*f'epsg:\{epsg_for_utm_zone\(zone, band\)\}'", src)
    assert m, 'RS_PROJECT_CRS must come from epsg_for_utm_zone(zone, band)'
