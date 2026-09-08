#!/usr/bin/env python3
"""Frozen-progress detection (NA165/H2060 zone_2, 2026-09-07).

WHY THIS EXISTS. zone_2 spent 11,880 s making provably zero progress and the
existing stall guard logged nothing. That guard keys on the progress LINE
changing (realityscan_cli, the `line != last_progress_line` branch); during the
freeze RealityScan emitted

    <alg> 0.61 39859.34 25128.00 #progress     <- fraction unchanged
    <alg> 0.61 40459.34 25506.00 #timeout      <- 600 s later, not "activity"
    <alg> 0.61 40468.86 25512.00 #progress     <- re-arms the timer

The elapsed counter advances on every line, so the text always differs, and
non-#timeout records arrived at most 800 s apart against a 7,200 s threshold.
The timer re-armed forever. The threshold is not the bug and cannot be tuned
around it: anything that would fire must sit under 800 s, and a HEALTHY align
is legitimately quiet for one 600 s -writeProgress heartbeat.

The discriminator is the recovered fraction p = elapsed / (elapsed + remaining),
which inverts RealityScan's own remaining = elapsed*(1-p)/p and resolves ~100x
finer than the two decimals in the line.

Numbers below are measured from the real logs, not invented.

Run:  python -m pytest testing/test_progress_stall.py
"""
from __future__ import annotations

import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO_ROOT)

from modules.realityscan_interface.realityscan_cli import (  # noqa: E402
    PROGRESS_STALL_EPSILON, PROGRESS_STALL_WINDOW_SECONDS, _ProgressTracker,
    parse_progress_line)


def line(alg, frac, elapsed, remaining, tag='#progress'):
    return 'RealityScan [RS1]: %d %.2f %.2f %.2f %s' % (
        alg, frac, elapsed, remaining, tag)


# --------------------------------------------------------------------- parse

def test_parses_a_real_progress_line():
    got = parse_progress_line(
        'INFO:__main__:RealityScan [RS1]: 65537 0.61 39859.34 25128.00 #progress')
    assert got == (65537, 0.61, 39859.34, 25128.00)


def test_parses_a_timeout_line_too():
    """#timeout records carry the same numbers and must NOT be discarded -
    during the freeze they were half the evidence that nothing moved."""
    got = parse_progress_line('RealityScan [RS1]: 65537 0.61 40459.34 25506.00 #timeout')
    assert got is not None and got[0] == 65537


@pytest.mark.parametrize('bad', [
    '', 'RealityScan [RS1]: starting', 'no numbers here',
    'INFO: some 1.5 line', 'RealityScan [RS1]: 65537 0.61',
])
def test_malformed_lines_never_raise(bad):
    """A monitor that dies on an unexpected line is worse than no monitor."""
    assert parse_progress_line(bad) is None


def test_recovered_fraction_inverts_realityscans_own_estimate():
    """remaining = elapsed*(1-p)/p, so p = elapsed/(elapsed+remaining)."""
    p = _ProgressTracker.recovered_fraction(39859.34, 25128.00)
    # 39859.34 / 64987.34 = 0.6133401 - note the line itself displayed "0.61",
    # which is the whole point: the printed figure cannot resolve the freeze.
    assert abs(p - 0.6133401) < 1e-6
    # ...and it resolves far finer than the printed "0.61".
    a = _ProgressTracker.recovered_fraction(39859.34, 25128.00)
    b = _ProgressTracker.recovered_fraction(51127.70, 32005.00)
    assert a != b


def test_degenerate_pairs_are_ignored_not_crashed():
    assert _ProgressTracker.recovered_fraction(0.0, 0.0) is None
    assert _ProgressTracker.recovered_fraction(-1.0, 5.0) is None


# ------------------------------------------------------------------ the freeze

def test_the_real_zone_2_freeze_trips():
    """Replays the measured freeze: p pinned near 0.615011 while elapsed runs
    on. Values jitter over a 6e-6 span and NON-MONOTONICALLY, which is why an
    equality test would never have fired."""
    t = _ProgressTracker()
    jitter = [0.615009278, 0.615015234, 0.615011002, 0.615013100,
              0.615010455, 0.615012877, 0.615011900]
    tripped = None
    elapsed = 39859.34
    for i in range(40):
        p = jitter[i % len(jitter)]
        remaining = elapsed * (1.0 - p) / p
        got = t.update(line(65537, 0.61, elapsed, remaining))
        if got and tripped is None:
            tripped = (elapsed, got)
        elapsed += 600.0
    assert tripped is not None, 'the freeze must be detected'
    frozen_at, span = tripped
    assert span >= PROGRESS_STALL_WINDOW_SECONDS
    # It must fire well before the 11,880 s the real freeze ran for.
    assert frozen_at - 39859.34 <= 5000.0


def test_a_healthy_run_never_trips():
    """zone_1's real shape: every record carried a strictly new fraction (182
    records, 182 distinct values across two runs)."""
    t = _ProgressTracker()
    elapsed = 10.0
    p = 0.01
    for _ in range(200):
        remaining = elapsed * (1.0 - p) / p
        assert t.update(line(65537, round(p, 2), elapsed, remaining)) is None
        elapsed += 120.0
        p = min(0.999, p + 0.005)


def test_a_600s_heartbeat_plateau_does_not_trip():
    """zone_1's longest LEGITIMATE plateau was 600.0 s / 603.2 s - exactly one
    -writeProgress heartbeat. The window must clear that comfortably."""
    t = _ProgressTracker()
    elapsed, p = 5000.0, 0.42
    for _ in range(6):                      # ~3,000 s of genuine quiet
        remaining = elapsed * (1.0 - p) / p
        assert t.update(line(65537, 0.42, elapsed, remaining)) is None
        elapsed += 500.0
    # ...then it moves again, as zone_1's did.
    for _ in range(5):
        p += 0.01
        remaining = elapsed * (1.0 - p) / p
        assert t.update(line(65537, round(p, 2), elapsed, remaining)) is None
        elapsed += 500.0


def test_slow_but_real_progress_never_trips():
    """The case the window must not mislabel: zone_2 WAS advancing for hours
    before the freeze, at ~1e-4 per 600 s. That has to survive."""
    t = _ProgressTracker()
    elapsed, p = 20000.0, 0.55
    for _ in range(60):
        remaining = elapsed * (1.0 - p) / p
        assert t.update(line(65537, round(p, 2), elapsed, remaining)) is None, \
            'genuine slow progress must not be called a stall'
        elapsed += 600.0
        p += 3e-4


def test_a_new_operation_resets_the_history():
    """A new algId restarts elapsed near zero; without a reset the delta
    against the previous operation is meaningless."""
    t = _ProgressTracker()
    elapsed, p = 40000.0, 0.615011
    for _ in range(12):
        remaining = elapsed * (1.0 - p) / p
        t.update(line(65537, 0.61, elapsed, remaining))
        elapsed += 600.0
    assert t.update(line(77824, 0.02, 30.0, 1470.0)) is None
    assert t.alg == 77824 and len(t.samples) == 1


def test_timeout_records_count_as_evidence_of_freezing():
    """The old guard EXCLUDED #timeout lines as non-activity, which is what let
    the alternation re-arm it. Here they must be counted."""
    t = _ProgressTracker()
    elapsed, p = 40000.0, 0.615011
    tripped = False
    for i in range(30):
        remaining = elapsed * (1.0 - p) / p
        tag = '#timeout' if i % 2 else '#progress'
        if t.update(line(65537, 0.61, elapsed, remaining, tag)):
            tripped = True
            break
        elapsed += 600.0
    assert tripped, 'alternating #timeout/#progress must not mask a freeze'


def test_epsilon_sits_above_the_measured_jitter():
    """Jitter across the real freeze spanned 5.96e-6; the smallest genuine
    increment just before it was ~9e-5."""
    assert PROGRESS_STALL_EPSILON > 6e-6 * 10
    assert PROGRESS_STALL_EPSILON <= 1e-4


# --------------------------------------------------------------------------
# B16 - the merge peel ceiling must be distinguishable from exhaustion
# --------------------------------------------------------------------------
# Same defect class as the align identity ceiling (B13), but worse in effect:
# the old cap jumped to :after_export, the NORMAL exit-0 label, and
# peel_counts_from walks identity_r<K> with an unbounded loop that stops at the
# first missing directory - so a cap at 40 and an exhaustion at 40 were
# byte-identical on disk. Those counts are what the fusion attribution assigns
# cameras with. NA165/H2060 finished its aligns with 43 components.

_MERGE_BAT = os.path.join(
    REPO_ROOT, 'modules', 'realityscan_interface', 'RS_CLI', 'Scripts',
    'MergeZoneComponents.bat')


def _merge_bat_text():
    with open(_MERGE_BAT, encoding='ascii', errors='replace') as fh:
        return fh.read()


def test_peel_ceiling_is_above_this_dive_component_count():
    """43 components across three zones already exceeded the old cap of 40."""
    import re as _re
    m = _re.search(r'^set "max_peel=(\d+)"', _merge_bat_text(), _re.M)
    assert m, 'MergeZoneComponents.bat no longer declares a max_peel default'
    assert int(m.group(1)) >= 60


def test_peel_ceiling_does_not_fall_into_the_normal_exit():
    """The whole defect: the cap used to `goto :after_export`, which is the
    clean exit-0 path, so nothing distinguished it from a finished scene."""
    text = _merge_bat_text()
    assert 'goto :peelCeiling' in text
    assert ':peelCeiling' in text
    assert 'if %peel_index% GEQ 40 goto :after_export' not in text


def test_peel_ceiling_writes_a_durable_marker():
    """peel_counts_from cannot infer truncation from the directories alone, so
    the .bat has to leave a signal it can read."""
    import re as _re
    # Split on the LABEL DEFINITION (line-initial), not the goto that
    # references it - the goto appears first and slicing there yields the loop
    # body instead of the ceiling block. Same trap as the AlignZone test.
    text = _merge_bat_text()
    block = _re.split(r'^:peelCeiling$', text, maxsplit=1, flags=_re.M)[1]
    block = _re.split(r'^:after_export$', block, maxsplit=1, flags=_re.M)[0]
    assert 'PEEL_TRUNCATED.txt' in block
    assert 'last_peeled' in block


def test_peel_counts_refuses_a_truncated_peel(tmp_path):
    """Scoring a truncated peel would silently mis-assign cameras, so it must
    raise rather than return a short list."""
    import merge_zones
    for k in range(3):
        d = tmp_path / f'identity_r{k}'
        d.mkdir()
        for i in range(5):
            (d / f'{i}.xmp').write_text('x', encoding='utf-8')
    assert merge_zones.peel_counts_from(str(tmp_path)) == [5, 5, 5]

    (tmp_path / 'PEEL_TRUNCATED.txt').write_text(
        'peel_ceiling_hit=120 last_peeled=119', encoding='utf-8')
    with pytest.raises(RuntimeError) as exc:
        merge_zones.peel_counts_from(str(tmp_path))
    assert 'INCOMPLETE' in str(exc.value)
    assert 'RS_MAX_PEEL_COMPONENTS' in str(exc.value)
