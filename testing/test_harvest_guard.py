#!/usr/bin/env python3
"""The reparse-point guard in front of the cross-zone merge.

The peel harvest is a PowerShell `Get-ChildItem -Recurse`, which does NOT
descend into junction CHILDREN, and RealityScan writes no XMP sidecars when a
scene's images resolve through a reparse point. Handing merge_zones.py an
image root whose children are junctions therefore yields an empty peel on
every attempt - indistinguishable from a legitimately empty scene, and it
silently discarded two full merge runs on 2026-07-27/28 (FINDINGS).

`assert_harvestable` exists so that failure mode costs seconds, not hours.
These tests pin it. They create a real NTFS junction via `mklink /J`, which
needs no elevation; if that is unavailable the junction case is skipped rather
than silently passing.

Run:  py -3.13 -m pytest testing/test_harvest_guard.py
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO_ROOT)

from modules import harvest_guard  # noqa: E402

LOG = logging.getLogger('test')


def make_junction(link: str, target: str) -> bool:
    """Create an NTFS junction. Returns False when the platform cannot."""
    if os.name != 'nt':
        return False
    result = subprocess.run(['cmd', '/c', 'mklink', '/J', link, target],
                            capture_output=True, text=True)
    return result.returncode == 0 and os.path.isdir(link)


def test_a_plain_directory_tree_is_harvestable(tmp_path):
    root = tmp_path / 'images'
    (root / 'zone_1' / 'cinema').mkdir(parents=True)
    (root / 'zone_2' / 'port').mkdir(parents=True)
    harvest_guard.assert_harvestable(str(root), LOG)   # must not raise


def test_an_empty_root_is_harvestable(tmp_path):
    root = tmp_path / 'empty'
    root.mkdir()
    harvest_guard.assert_harvestable(str(root), LOG)


def test_a_junction_child_is_refused(tmp_path):
    real = tmp_path / 'real' / 'zone_1'
    real.mkdir(parents=True)
    (real / 'a.jpg').write_bytes(b'x')

    root = tmp_path / 'view'
    root.mkdir()
    if not make_junction(str(root / 'zone_1'), str(real)):
        pytest.skip('cannot create an NTFS junction here')

    with pytest.raises(RuntimeError, match='reparse-point children'):
        harvest_guard.assert_harvestable(str(root), LOG)


def test_a_nested_junction_is_also_refused(tmp_path):
    """A junction one level down (zone_1/cinema) blinds the harvest exactly
    like a top-level one - the guard must scan recursively (final review)."""
    real = tmp_path / 'real' / 'cinema'
    real.mkdir(parents=True)
    (real / 'a.jpg').write_bytes(b'x')

    root = tmp_path / 'view'
    (root / 'zone_1').mkdir(parents=True)
    if not make_junction(str(root / 'zone_1' / 'cinema'), str(real)):
        pytest.skip('cannot create an NTFS junction here')

    with pytest.raises(RuntimeError, match='reparse-point children'):
        harvest_guard.assert_harvestable(str(root), LOG)


def test_the_refusal_names_the_offending_children(tmp_path):
    """A guard that fires without saying what to fix costs another run."""
    real = tmp_path / 'real'
    (real / 'zone_3').mkdir(parents=True)
    (real / 'zone_5').mkdir(parents=True)

    root = tmp_path / 'view'
    root.mkdir()
    made = [make_junction(str(root / z), str(real / z))
            for z in ('zone_3', 'zone_5')]
    if not all(made):
        pytest.skip('cannot create an NTFS junction here')

    with pytest.raises(RuntimeError) as excinfo:
        harvest_guard.assert_harvestable(str(root), LOG)
    message = str(excinfo.value)
    assert 'zone_3' in message and 'zone_5' in message


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
