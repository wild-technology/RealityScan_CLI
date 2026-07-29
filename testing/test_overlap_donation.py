#!/usr/bin/env python3
"""The overlap-donation cap and distance ceiling (2026-07-28).

Regression cover for the zoning-nullification defect: the donation slice
`np.argsort(score)[:overlap_size]` was sized only by the RECEIVER (20% of the
zone) with no reference to the donor pool, so a large zone swallowed most of
everything else. Measured on H2023: zone_1 ended with 4,540 of 4,598 unique
images - 98.7% of the dive, spanning all three co-visibility blocks, 756 of
its images structurally unable to match its own main block.

The fix is a symmetric cap (at most overlap%% of the receiver AND of the donor
pool) plus an optional absolute distance ceiling (0 = legacy uncapped, band
width deliberately unsettled pending the overlap probe).

These tests drive __create_geographic_zones directly on a synthetic two-strip
survey. No RealityScan.

Run:  py -3.13 -m pytest testing/test_overlap_donation.py
"""

from __future__ import annotations

import logging
import os
import sys

import numpy as np
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO_ROOT)

gpd = pytest.importorskip('geopandas')
from shapely.geometry import Point  # noqa: E402

from modules.image_batcher.batch_directory import BatchDirectory  # noqa: E402


def survey_gdf(n_a=300, n_b=60, gap_m=200.0):
    """Two parallel survey strips separated by `gap_m` - far beyond any
    plausible overlap band, so every cross-strip donation is pure pathology."""
    rng = np.random.default_rng(7)
    ax = rng.uniform(0, 60, n_a)
    ay = rng.uniform(0, 8, n_a)
    bx = rng.uniform(0, 20, n_b)
    by = rng.uniform(gap_m, gap_m + 8, n_b)
    xs = np.concatenate([ax, bx])
    ys = np.concatenate([ay, by])
    names = [f'img_{i:04d}.jpg' for i in range(n_a + n_b)]
    return gpd.GeoDataFrame(
        {'filename': names},
        geometry=[Point(x, y) for x, y in zip(xs, ys)])


def make_zones(gdf, overlap_percent, max_distance):
    mod = BatchDirectory(logging.getLogger('test'))
    zones, base, _ = mod._BatchDirectory__create_geographic_zones(
        gdf, target_size=200, min_size=10, max_size=400,
        overlap_percent=overlap_percent, density_weight=0.3, kde_bw=0.0,
        max_overlap_distance_m=max_distance)
    return zones, base


def test_donor_pool_cap_limits_the_big_zone():
    """The big strip must not swallow the small one: its donation is capped at
    overlap%% of the DONOR pool, not sized purely by its own bulk."""
    gdf = survey_gdf()
    zones, base = make_zones(gdf, overlap_percent=20.0, max_distance=0.0)
    assert len(zones) >= 2, 'two strips must become at least two zones'
    for files, base_files in zip(zones, base.values()):
        donated = len(files) - len(base_files)
        donor_pool = len(gdf) - len(base_files)
        cap = int(donor_pool * 0.20)
        assert donated <= cap, (
            f'zone with {len(base_files)} base images donated {donated}, '
            f'over the donor-pool cap of {cap}')


def test_no_zone_holds_practically_the_whole_dive():
    """The H2023 shape: one zone ending with ~99% of unique images."""
    gdf = survey_gdf()
    zones, _ = make_zones(gdf, overlap_percent=20.0, max_distance=0.0)
    unique = len(gdf)
    biggest = max(len(set(z)) for z in zones)
    assert biggest / unique < 0.95, (
        f'one zone holds {biggest} of {unique} unique images - '
        'zoning nullified')


def test_distance_ceiling_blocks_cross_strip_donation():
    """With a ceiling far below the 200 m strip gap, zero cross-strip images
    may be donated in either direction."""
    gdf = survey_gdf()
    zones, base = make_zones(gdf, overlap_percent=20.0, max_distance=10.0)
    coords = {row.filename: (row.geometry.x, row.geometry.y)
              for row in gdf.itertuples()}
    for files, base_files in zip(zones, base.values()):
        base_ys = [coords[f][1] for f in base_files]
        strip_is_north = (sum(base_ys) / len(base_ys)) > 100.0
        for f in set(files) - set(base_files):
            donated_north = coords[f][1] > 100.0
            assert donated_north == strip_is_north, (
                f'{f} was donated across a 200 m gap despite a 10 m ceiling')


def test_ceiling_zero_keeps_legacy_reach():
    """0 disables the ceiling (band width is an open question - the cap alone
    must be what changed default behaviour)."""
    gdf = survey_gdf(gap_m=30.0)
    zones_uncapped, base = make_zones(gdf, overlap_percent=20.0,
                                      max_distance=0.0)
    donated = sum(len(f) - len(b)
                  for f, b in zip(zones_uncapped, base.values()))
    assert donated > 0, 'donation itself must still function'


def test_show_plots_is_opt_in(monkeypatch):
    """plt.show must never run without RS_SHOW_PLOTS=1 - isatty() lies under
    hidden consoles and blocked the batcher for hours."""
    import modules.image_batcher.batch_directory as bd
    called = []
    monkeypatch.setattr(bd.plt, 'show', lambda: called.append(True))
    monkeypatch.delenv('RS_SHOW_PLOTS', raising=False)
    BatchDirectory._show_if_interactive()
    assert not called, 'no opt-in, no show()'
    monkeypatch.setenv('RS_SHOW_PLOTS', '1')
    BatchDirectory._show_if_interactive()
    assert called, 'explicit opt-in must show'


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
