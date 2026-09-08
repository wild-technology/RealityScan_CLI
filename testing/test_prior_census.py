#!/usr/bin/env python3
"""The priors-landed gate (NA165/H2060, 2026-09-08).

WHY THIS EXISTS. Four zones, 19,241 images, per-camera prior groups
configured, and every exported camera came back CalibrationGroup="-1" with
1,700 distinct solved focals across 3,000 cameras. Every channel said
success: the delegated command returned 0, prior_groups logged "1 camera
family", AlignZone.bat's :run saw no error, the run exited clean. The only
place the failure was visible was the solve itself, and nothing looked.

The fixtures below are shaped from the REAL measurements, not invented:
  - the failure   = zone_1's harvest, CalibrationGroup=-1 and free focals
  - the pass      = the 2026-08-08 -addImageWithCalibration probe, which
                    echoed groups 5/6 with focals identical within each eye

Run:  python -m pytest testing/test_prior_census.py
"""
from __future__ import annotations

import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO_ROOT)

from modules.prior_census import (  # noqa: E402
    MAX_DISTINCT_FOCAL_FRACTION, MAX_UNGROUPED_FRACTION,
    MIN_CAMERAS_FOR_FOCAL_TEST, PriorsNotApplied, assert_priors_landed,
    census)

XMP = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
    '  <rdf:Description xcr:Version="4" xcr:PosePrior="initial"\n'
    '     xcr:FocalLength35mm="{focal}"\n'
    '     xcr:CalibrationGroup="{group}" xcr:DistortionGroup="{group}">\n'
    '    <xcr:Position>1 2 3</xcr:Position>\n'
    '  </rdf:Description>\n'
    '</x:xmpmeta>\n')


def _harvest(tmp_path, entries, name='identity_r0'):
    d = tmp_path / name
    d.mkdir()
    for i, (group, focal) in enumerate(entries):
        (d / f'cam{i:05d}.xmp').write_text(
            XMP.format(group=group, focal=focal), encoding='utf-8')
    return str(d)


# --------------------------------------------------------------- the failure

def test_the_real_na165_failure_is_refused(tmp_path):
    """zone_1's measured shape: every camera ungrouped, every focal its own."""
    entries = [(-1, 8.9 + i * 0.37) for i in range(200)]
    h = _harvest(tmp_path, entries)
    with pytest.raises(PriorsNotApplied) as exc:
        assert_priors_landed(h, context='zone_1')
    msg = str(exc.value)
    assert 'CalibrationGroup=-1' in msg
    assert 'self-calibrated' in msg
    # It must also name the SECOND symptom, so a reader who fixes only the
    # group echo does not think the job is done.
    assert 'distinct solved focal' in msg
    assert 'zone_1' in msg


def test_a_working_delivery_passes(tmp_path):
    """The 2026-08-08 probe shape: groups echo, focals identical within group.

    The two eyes solved to 24.1982 and 24.1966 - 0.0016 mm apart - so the
    2 dp rounding collapses them to ONE distinct focal. That is the rounding
    working as intended, not a miscount: the focal test exists to catch
    per-image self-calibration, which spreads over MILLIMETRES (this dive
    measured 8.9-4,640 mm), and it must not try to resolve two near-identical
    lenses. Distinguishing groups that solved to the same focal is the GROUP
    census's job, which is why expected_groups reads `groups`, not focals."""
    entries = [(5, 24.1982)] * 100 + [(6, 24.1966)] * 100
    stats = assert_priors_landed(_harvest(tmp_path, entries), context='ok',
                                 expected_groups=2)
    assert stats['ungrouped'] == 0
    assert stats['distinct_focals'] == 1
    assert stats['groups'] == {5: 100, 6: 100}


# ------------------------------------------------------- neither test alone

def test_group_echo_alone_does_not_excuse_self_calibration(tmp_path):
    """A build that reports a group id and self-calibrates anyway must still
    be caught - which the -1 test alone would miss entirely."""
    entries = [(1, 10.0 + i * 0.5) for i in range(200)]
    with pytest.raises(PriorsNotApplied) as exc:
        assert_priors_landed(_harvest(tmp_path, entries), context='z')
    assert 'distinct solved focal' in str(exc.value)
    assert 'CalibrationGroup=-1' not in str(exc.value)


def test_a_few_ungrouped_stragglers_are_tolerated(tmp_path):
    """RealityScan leaving the odd camera unattributed is normal; only a
    wholesale failure is the defect. NA165/H2060 measured 100.0%."""
    n = 200
    bad = int(n * MAX_UNGROUPED_FRACTION) - 1
    entries = [(-1, 23.0)] * bad + [(1, 23.0)] * (n - bad)
    assert_priors_landed(_harvest(tmp_path, entries), context='z')


def test_the_ungrouped_limit_actually_bites_just_above_it(tmp_path):
    n = 200
    bad = int(n * MAX_UNGROUPED_FRACTION) + 2
    entries = [(-1, 23.0)] * bad + [(1, 23.0)] * (n - bad)
    with pytest.raises(PriorsNotApplied):
        assert_priors_landed(_harvest(tmp_path, entries), context='z')


def test_a_fragmented_zone_is_not_mistaken_for_self_calibration(tmp_path):
    """The false positive that would make this gate useless. Each COMPONENT
    self-calibrates, so zone_1's 33 components over 7,655 cameras give 33
    distinct focals - 0.4%, three orders of magnitude under the limit. A
    fragmented but correctly-grouped zone must sail through."""
    entries = []
    for comp in range(33):
        entries += [(1, 23.0 + comp * 0.01)] * 230
    stats = assert_priors_landed(_harvest(tmp_path, entries), context='z')
    assert stats['distinct_focals'] == 33
    assert stats['distinct_focal_fraction'] < MAX_DISTINCT_FOCAL_FRACTION


# ------------------------------------------------------------ absent evidence

def test_an_empty_harvest_is_a_failure_not_a_pass(tmp_path):
    """"Unmeasured" is the state that let NA165/H2060 ship. It is not a pass."""
    d = tmp_path / 'identity_r0'
    d.mkdir()
    with pytest.raises(PriorsNotApplied) as exc:
        assert_priors_landed(str(d), context='zone_2')
    assert 'CANNOT BE DETERMINED' in str(exc.value)


def test_a_missing_directory_is_also_a_failure(tmp_path):
    with pytest.raises(PriorsNotApplied):
        assert_priors_landed(str(tmp_path / 'nope'), context='zone_2')


def test_a_tiny_harvest_skips_the_focal_test_but_not_the_group_test(tmp_path):
    """Below the sample floor the focal FRACTION is noise - but an all-
    ungrouped scene is unambiguous at any size."""
    small = MIN_CAMERAS_FOR_FOCAL_TEST - 5
    ok = [(1, 20.0 + i) for i in range(small)]          # every focal distinct
    assert_priors_landed(_harvest(tmp_path, ok, 'a'), context='z')
    bad = [(-1, 23.0) for _ in range(small)]
    with pytest.raises(PriorsNotApplied):
        assert_priors_landed(_harvest(tmp_path, bad, 'b'), context='z')


# --------------------------------------------------------------- multi-camera
# The directive is per-CAMERA grouping, so a rig whose cameras all collapsed
# into ONE group is a failure even though every group echo is valid and every
# focal agrees. Without this the gate would pass the exact state the WCA
# sidecars existed to prevent: four EXIF-identical cameras calibrated as one.

def test_cameras_merged_into_one_group_is_refused(tmp_path):
    entries = [(1, 16.0)] * 400
    with pytest.raises(PriorsNotApplied) as exc:
        assert_priors_landed(_harvest(tmp_path, entries), context='wca',
                             expected_groups=4)
    assert 'merged into one group' in str(exc.value)


def test_expected_groups_is_satisfied_when_they_are_all_present(tmp_path):
    entries = ([(1, 23.0)] * 60 + [(2, 16.0)] * 60
               + [(3, 16.1)] * 60 + [(4, 16.2)] * 60)
    assert_priors_landed(_harvest(tmp_path, entries), context='wca',
                         expected_groups=4)


def test_single_camera_dive_is_not_a_no_op(tmp_path):
    """The directive's real trap: on a one-camera dive expected_groups=1 is
    trivially satisfiable, so the gate must still fail on the focal spread.
    NA165/H2060 is exactly this shape - one family, zeuss."""
    entries = [(1, 9.0 + i * 0.31) for i in range(200)]
    with pytest.raises(PriorsNotApplied) as exc:
        assert_priors_landed(_harvest(tmp_path, entries), context='zone_2',
                             expected_groups=1)
    assert 'per-image self-calibration' in str(exc.value)


# ------------------------------------------------------------------- census

def test_census_reports_without_judging(tmp_path):
    """Callers that only want to LOG the state must not have to catch."""
    entries = [(-1, 23.0)] * 10
    stats = census(_harvest(tmp_path, entries))
    assert stats['cameras'] == 10
    assert stats['ungrouped'] == 10
    assert stats['ungrouped_fraction'] == 1.0


def test_an_xmp_with_no_group_attribute_is_counted_separately(tmp_path):
    """"Absent" and "explicitly -1" are different failures; folding them
    together would hide which one happened."""
    d = tmp_path / 'identity_r0'
    d.mkdir()
    (d / 'a.xmp').write_text('<rdf:Description xcr:FocalLength35mm="23.0"/>',
                             encoding='utf-8')
    stats = census(str(d))
    assert stats['groups'].get('absent') == 1
    assert stats['ungrouped'] == 0
