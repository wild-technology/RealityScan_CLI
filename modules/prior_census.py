"""Did the calibration priors actually land? Census the SOLVE, not the input.

WHY THIS EXISTS
---------------
NA165/H2060 aligned 19,241 images across four zones with per-camera prior
groups configured, and not one camera received them. Measured 2026-09-08 on
3,000 harvested pose XMPs from zone_1:

    xcr:CalibrationGroup="-1"   3000 / 3000
    xcr:DistortionGroup="-1"    3000 / 3000
    distinct FocalLength35mm    1,700 across 3,000 cameras
    range                       8.947 mm .. 4,640.580 mm  (prior: 23.0)

That is per-image self-calibration - every camera free to invent its own
focal. Focal length and scale are the same degree of freedom in a monocular
solve, so the scale gate then failed 35 of 43 components, two of them at
EXACTLY 2.00 (the focal doubling showing up as a scale doubling), and the
merge could not pair anything: all 43 clusters came out as singletons.

Every channel reported success. `-setPriorCalibrationGroup` returned 0,
`prior_groups.write_command_file` logged "1 camera family", AlignZone.bat's
`:run` saw no error, and the run exited clean. FINDINGS 2026-08-08 had
already established the mechanism is "silently NON-FUNCTIONAL from the
delegated CLI" and CalibCellAlign.bat:93 calls it RETIRED - but the main
align path still used it, and nothing anywhere checked the result.

THE PRINCIPLE. A prior that cannot be observed in the output is not a prior,
it is a hope. Configuring one is not evidence it applied; the only evidence
is the solve. This module reads what RealityScan actually did and refuses the
run when the answer is "nothing".

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
It does not check that solved focals match the PRIOR VALUE. The calibration
ladder (FINDINGS 2026-08-09) measured full manufacturer priors COLLAPSING
registration - 97.3% control / 97.7% groups-only / 45.4% with values - and
run3 (2026-08-28) measured them corrupting metric scale by -2.55% while
steering solved focal away from both the prior and RealityScan's own free
solve. Groups-only was the best arm on both. So GROUPING is the contract
here; the numeric value is not, and asserting it would enforce the arm that
was measured to be harmful.
"""
from __future__ import annotations

import collections
import glob
import logging
import os
import re

logger = logging.getLogger(__name__)

# xcr:CalibrationGroup="-1" is RealityScan's "this camera belongs to no
# calibration group", i.e. it self-calibrated. Exported as a plain attribute.
_GROUP_RE = re.compile(r'xcr:CalibrationGroup="(-?\d+)"')
_DGROUP_RE = re.compile(r'xcr:DistortionGroup="(-?\d+)"')
_FOCAL_RE = re.compile(r'xcr:FocalLength35mm="([0-9.eE+-]+)"')

UNGROUPED = -1

# Fraction of cameras allowed to carry CalibrationGroup=-1 before the run is
# refused. Not zero: a camera RealityScan could not attribute to any group is
# a normal straggler. A wholesale failure is a different shape entirely -
# NA165/H2060 measured 100.0%, and a working delivery measured 0% (the
# 2026-08-08 -addImageWithCalibration probe echoed groups 5/6 on every camera).
MAX_UNGROUPED_FRACTION = 0.10

# Distinct solved focals as a fraction of cameras. Per-image self-calibration
# drives this toward 1.0 (NA165/H2060 zone_1 measured 0.57 after rounding to
# 2 dp); working grouping drives it toward components/cameras, which is small
# even on a heavily fragmented zone - zone_1's 33 components over 7,655
# cameras would be 0.004. The gap is three orders of magnitude, so the
# threshold is not delicate.
MAX_DISTINCT_FOCAL_FRACTION = 0.25

# Below this, the fractions above are noise rather than evidence.
MIN_CAMERAS_FOR_FOCAL_TEST = 30


class PriorsNotApplied(RuntimeError):
    """The solve shows the calibration priors were never applied."""


def census(harvest_dir: str) -> dict:
    """What the SOLVE used, read from the exported pose XMPs.

    `harvest_dir` is an identity_r<K> directory (or any directory of pose
    XMPs). Returns counts rather than raising - `assert_priors_landed` makes
    the judgement, so a caller that only wants to LOG the state can.
    """
    paths = sorted(glob.glob(os.path.join(harvest_dir, '*.xmp')))
    groups: collections.Counter = collections.Counter()
    dgroups: collections.Counter = collections.Counter()
    focals: list[float] = []
    unreadable = 0

    for path in paths:
        try:
            with open(path, encoding='utf-8', errors='replace') as fh:
                text = fh.read()
        except OSError:
            unreadable += 1
            continue
        m = _GROUP_RE.search(text)
        # A pose XMP with no CalibrationGroup attribute at all is counted
        # separately rather than folded into -1: "absent" and "explicitly
        # ungrouped" are different failures and the message should say which.
        groups[int(m.group(1)) if m else 'absent'] += 1
        m = _DGROUP_RE.search(text)
        if m is not None:
            dgroups[int(m.group(1))] += 1
        m = _FOCAL_RE.search(text)
        if m is not None:
            try:
                focals.append(float(m.group(1)))
            except ValueError:
                pass

    cameras = len(paths) - unreadable
    ungrouped = groups.get(UNGROUPED, 0)
    # Rounded to 2 dp: two cameras in one group solve to the same focal to
    # far better than 0.01 mm, so rounding cannot merge genuinely distinct
    # groups but does absorb float noise.
    distinct_focals = len({round(f, 2) for f in focals})

    return {
        'harvest_dir': harvest_dir,
        'cameras': cameras,
        'unreadable': unreadable,
        'groups': dict(groups),
        'distortion_groups': dict(dgroups),
        'ungrouped': ungrouped,
        'ungrouped_fraction': (ungrouped / cameras) if cameras else 0.0,
        'distinct_focals': distinct_focals,
        'distinct_focal_fraction': (distinct_focals / cameras) if cameras else 0.0,
        'focal_min': min(focals) if focals else None,
        'focal_max': max(focals) if focals else None,
    }


def assert_priors_landed(harvest_dir: str, *, context: str = '',
                         expected_groups: int | None = None) -> dict:
    """Refuse the run when the solve shows the priors were never applied.

    Raises `PriorsNotApplied` with the census in the message. Two independent
    tests, because either alone has a blind spot: the group echo is direct
    evidence but RealityScan may legitimately leave stragglers ungrouped,
    while the focal spread is indirect but catches a build that reports a
    group id and self-calibrates anyway.

    An EMPTY harvest is not a pass. It is the same "no evidence" state that
    let NA165/H2060 ship, so it raises too - a caller that genuinely has no
    harvest should not be calling this.
    """
    where = context or harvest_dir
    stats = census(harvest_dir)

    if not stats['cameras']:
        raise PriorsNotApplied(
            f'{where}: no pose XMPs under {harvest_dir}, so whether the '
            'calibration priors applied CANNOT BE DETERMINED. Refusing to '
            'treat unmeasured as passing - that is exactly how NA165/H2060 '
            'shipped 19,241 images with no priors at all.')

    problems: list[str] = []

    if stats['ungrouped_fraction'] > MAX_UNGROUPED_FRACTION:
        problems.append(
            'CalibrationGroup=-1 on {n}/{c} cameras ({f:.1%}, limit {lim:.0%}) '
            '- the solve self-calibrated instead of using the prior groups'
            .format(n=stats['ungrouped'], c=stats['cameras'],
                    f=stats['ungrouped_fraction'], lim=MAX_UNGROUPED_FRACTION))

    if (stats['cameras'] >= MIN_CAMERAS_FOR_FOCAL_TEST
            and stats['distinct_focal_fraction'] > MAX_DISTINCT_FOCAL_FRACTION):
        problems.append(
            '{d} distinct solved focal lengths across {c} cameras ({f:.1%}, '
            'limit {lim:.0%}), spanning {lo:.2f}-{hi:.2f} mm - that is '
            'per-image self-calibration, not grouped calibration'
            .format(d=stats['distinct_focals'], c=stats['cameras'],
                    f=stats['distinct_focal_fraction'],
                    lim=MAX_DISTINCT_FOCAL_FRACTION,
                    lo=stats['focal_min'] or 0.0, hi=stats['focal_max'] or 0.0))

    if expected_groups is not None:
        seen = {g for g in stats['groups'] if isinstance(g, int) and g != UNGROUPED}
        if seen and len(seen) < expected_groups:
            problems.append(
                f'{len(seen)} calibration group(s) present in the solve '
                f'({sorted(seen)}) but {expected_groups} camera(s) were '
                'configured - cameras that should calibrate separately have '
                'been merged into one group')

    if problems:
        raise PriorsNotApplied(
            '{where}: the calibration priors did NOT reach the solve.\n'
            '  {problems}\n'
            '  Census: {stats}\n'
            '  This is a CRITICAL error by owner directive (2026-09-08): '
            'camera priors must win, and a run that silently self-calibrates '
            'produces free per-camera focal length, therefore free scale, '
            'therefore components that cannot be merged. Do not re-run until '
            'the prior delivery channel is fixed; re-running changes nothing.'
            .format(where=where, problems='\n  '.join(problems), stats=stats))

    logger.info('Calibration priors verified in the solve for %s: %d cameras, '
                'groups %s, %d distinct focal length(s)', where,
                stats['cameras'], stats['groups'], stats['distinct_focals'])
    return stats
