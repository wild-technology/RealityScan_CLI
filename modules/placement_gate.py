#!/usr/bin/env python3
"""Refuse to publish a component whose computed placement is not credible.

WHY THIS EXISTS (ported from NA165/H2060 _agent/export/placement_check.py,
2026-09-21). publish_cesium reads each mesh's own .rsInfo sidecar to work out
where the mesh is. On 2026-09-14 that sidecar was believed while it answered a
different question from the one being asked:

    globalCoordinateSystemName="epsg:32702 - WGS 84 / UTM zone 2S"
    exportCoordinateSystemType="3"      <- vertices are actually ECEF

Reading the name as the vertex frame put the anchor at lon 90.45, lat -38.49,
depth -1,555,435 m - the Indian Ocean, 1,555 km down - for a dive off American
Samoa at 690 m. The fix (cesium_placement._geocentric_to_projected) was
verified on ONE 52-camera component; this gate is what runs it on all of them.

The check is against something plan_placement does not derive from the mesh
at all: the flight log's nav envelope. Two independent sources agreeing is
evidence; the sidecar agreeing with itself is not.

GENERIC, where the dive-local original was not: its bounds were this dive's
numbers (5 km from the nav CENTRE; depth -1200..-300 m for a 643-689 m
seabed). Here both come from the flight log:

  horizontal  the anchor may lie at most --max-outside-m OUTSIDE the nav
              envelope's E/N box (0 m when inside). On NA165/H2060 all eight
              components measured sat inside it (0.0 m); the centre-distance
              the old gate used was 29-258 m.
  depth       the anchor Z must lie within the nav depth range widened by
              --depth-margin-m on both sides. The margin absorbs the seabed
              lying below the vehicle AND the datum difference for geocentric
              exports, whose Z is an ELLIPSOIDAL height while nav is MSL
              (|N| < ~110 m anywhere on EGM2008).

WHAT IT DOES NOT CHECK. Orientation and scale. A mesh can be centred
correctly while rotated or mis-scaled - the delivered zone_2_c18 is a 70-camera
component whose OBJ spans 0.3 x 0.5 x 0.3 m and passes both checks. A pass means
"the placement is not obviously wrong", never "the placement is correct".
--min-extent-m (off by default) is a COLLAPSE check: it fails when the LARGER
of the two horizontal extents is under the limit, i.e. when the mesh is small
in both directions. A long, thin component (0.2 x 10 m) passes it.

OFFLINE BY DESIGN. The gate compares anchor_projected - the mesh's own frame
Z, never the ellipsoidal height ion is given - so it asks plan_placement for
no geoid correction and never turns PROJ networking on (publish_cesium does
that when it needs the EGM2008 grid). A geocentric export needs no grid at all.

Exit 0 pass, 1 fail (including a placement that cannot be computed from the
mesh), 2 usage/input error (no such --dir, unreadable --flight-log).

Usage:
    python -m modules.placement_gate --dir <component>/obj --flight-log <log>
        [--max-outside-m 250] [--depth-margin-m 250] [--min-extent-m 0]
        [--json <out.json>]
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from modules import cesium_placement  # noqa: E402
from modules.cesium_placement import (  # noqa: E402
    PlacementError, nav_envelope_from_flight_log, plan_placement,
)

DEFAULT_MAX_OUTSIDE_M = 250.0
DEFAULT_DEPTH_MARGIN_M = 250.0


def outside_envelope_m(east: float, north: float, nav: dict) -> float:
    """Horizontal distance from (east, north) to the nav E/N box; 0 inside."""
    dx = max(nav['east'][0] - east, 0.0, east - nav['east'][1])
    dy = max(nav['north'][0] - north, 0.0, north - nav['north'][1])
    return math.hypot(dx, dy)


def check_plan(plan: dict, nav: dict,
               max_outside_m: float = DEFAULT_MAX_OUTSIDE_M,
               depth_margin_m: float = DEFAULT_DEPTH_MARGIN_M,
               min_extent_m: float = 0.0) -> tuple[dict, list[str]]:
    """(measurements, failures) for one placement plan against the nav."""
    east, north, z = plan['anchor_projected']
    outside = outside_envelope_m(east, north, nav)
    low = nav['alt'][0] - depth_margin_m
    high = nav['alt'][1] + depth_margin_m
    extent = plan.get('extent_m') or [0.0, 0.0, 0.0]
    measured = {
        'anchor_projected': [east, north, z],
        'outside_envelope_m': outside,
        'depth_band_m': [low, high],
        'z_is_ellipsoidal': str(plan.get('geoid_model', '')).startswith('NONE (geocentric'),
        'extent_m': list(extent),
    }
    failures = []
    if outside > max_outside_m:
        failures.append(
            f'anchor is {outside:.0f} m outside the nav envelope (limit '
            f'{max_outside_m:.0f} m). The mesh is not where the dive was.')
    if not (low <= z <= high):
        failures.append(
            f'anchor Z {z:.1f} m is outside the nav depth band '
            f'{low:.0f}..{high:.0f} m. The vertical is being read wrong.')
    if min_extent_m > 0 and max(extent[:2]) < min_extent_m:
        failures.append(
            f'horizontal extent {extent[0]:.2f} x {extent[1]:.2f} m is under '
            f'{min_extent_m:.2f} m in BOTH directions - a collapsed or '
            'mis-scaled solve.')
    return measured, failures


def _plan_quietly(objs, nav):
    """plan_placement without the geoid step, and without its warning that
    the asset 'WILL be placed wrong' - true of an ion upload, meaningless for
    a gate that reads anchor_projected and uploads nothing."""
    log = cesium_placement.logger
    level = log.level
    log.setLevel(logging.ERROR)
    try:
        return plan_placement(objs, nav_envelope=nav, apply_geoid=False)
    finally:
        log.setLevel(level)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--dir', required=True, help='component obj/ directory')
    ap.add_argument('--flight-log', required=True,
                    help='zone-tagged flight log of the dive (X/Y/Alt columns)')
    ap.add_argument('--max-outside-m', type=float, default=DEFAULT_MAX_OUTSIDE_M)
    ap.add_argument('--depth-margin-m', type=float, default=DEFAULT_DEPTH_MARGIN_M)
    ap.add_argument('--min-extent-m', type=float, default=0.0)
    ap.add_argument('--json', default=None, help='write the verdict here')
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0

    if not Path(args.dir).is_dir():
        print('ERROR: --dir %s is not a directory' % args.dir)
        return 2
    objs = sorted(Path(args.dir).glob('*.obj'))
    if not objs:
        print('FAIL: no .obj files in %s' % args.dir)
        return 1
    try:
        nav = nav_envelope_from_flight_log(Path(args.flight_log))
    except (OSError, ValueError, PlacementError) as exc:
        print('ERROR: cannot read the nav envelope from --flight-log %s: %s'
              % (args.flight_log, exc))
        return 2
    try:
        # plan_placement returns (plan, localised_vertices); only the plan is
        # wanted - nothing is written, this gate never rewrites a mesh.
        plan, _localised = _plan_quietly(objs, nav)
    except (OSError, PlacementError) as exc:
        print('FAIL: placement could not be computed: %s' % exc)
        return 1

    measured, failures = check_plan(plan, nav, args.max_outside_m,
                                    args.depth_margin_m, args.min_extent_m)
    e, n, z = measured['anchor_projected']
    print('component      : %s (%d obj part(s), %d vertices)'
          % (Path(args.dir).parent.name, len(objs), plan['vertex_count']))
    print('CRS            : %s' % plan['crs'])
    print('anchor         : lon %.6f  lat %.6f  E %.1f  N %.1f'
          % (plan['lon'], plan['lat'], e, n))
    print('anchor Z       : %.1f m (%s)   nav depth band %.0f..%.0f m'
          % (z, 'ellipsoidal' if measured['z_is_ellipsoidal'] else 'MSL',
             *measured['depth_band_m']))
    print('outside nav    : %.1f m   (limit %.0f m)'
          % (measured['outside_envelope_m'], args.max_outside_m))
    print('extent         : %.2f x %.2f x %.2f m' % tuple(measured['extent_m'][:3]))
    if args.json:
        Path(args.json).write_text(json.dumps(
            {'dir': args.dir, 'plan': plan, 'measured': measured,
             'failures': failures, 'pass': not failures}, indent=2),
            encoding='utf-8')
    if failures:
        for f in failures:
            print('FAIL: %s' % f)
        return 1
    print('PASS: placement is consistent with the flight log. '
          '(Orientation and scale are NOT checked - see the module docstring.)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
