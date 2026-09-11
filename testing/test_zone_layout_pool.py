#!/usr/bin/env python3
"""Zone layout 'pool' (owner directive 2026-08-08, FLIGHTLOG_ARCHITECTURE).

The copy layout materializes overlap donation as per-zone physical
copies, so the same survey image is a DIFFERENT camera in every zone it
belongs to and overlapping-zone components share nothing at merge time
(the known merge no-fuse defect). Pool layout writes NO zone images:
each zone gets an .imagelist of complete canonical source paths and a
flight log whose filename column carries those SAME full paths, so an
overlap image is one shared camera everywhere.

Offline: no RealityScan; exercises __create_batch_folders directly.

Run:  py -3.13 -m pytest testing/test_zone_layout_pool.py
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO_ROOT)

pytest.importorskip('pandas')
pytest.importorskip('geopandas')

from modules.image_batcher.batch_directory import BatchDirectory  # noqa: E402
from modules import camera_registry  # noqa: E402

QUIET = logging.getLogger('pool-test')
QUIET.addHandler(logging.NullHandler())
QUIET.propagate = False

HEADER = ('filename;x;y;alt;x_acc;y_acc;alt_acc;yaw;pitch;roll;'
          'yaw_acc;pitch_acc;roll_acc')


def _module(layout=None):
    module = BatchDirectory(QUIET)
    module.params = module.get_parameters()
    if layout is not None:
        module.params['batch_zone_layout'].set_value(layout)
    module.utm_zone_suffix = ''
    return module


def _write_log(path, names):
    rows = [HEADER]
    for i, name in enumerate(names):
        rows.append(f'{name};{100 + i};{200 + i};-5;0.02;0.02;0.02;'
                    f'90;45;0;10;10;10')
    path.write_text('\n'.join(rows) + '\n', encoding='utf-8')
    return path


def _source(tmp_path, names):
    src = tmp_path / 'src'
    src.mkdir(exist_ok=True)
    for n in names:
        (src / n).write_bytes(b'j')
    return src


def test_pool_zone_has_imagelist_and_fullpath_log_but_no_images(tmp_path):
    names = ['A.jpg', 'B.jpg', 'C.jpg']
    src = _source(tmp_path, names)
    log = _write_log(tmp_path / 'master.txt', names)
    out = tmp_path / 'batched'
    out.mkdir()
    module = _module('pool')
    # B.jpg is the overlap image: donated to BOTH zones.
    zones = [['A.jpg', 'B.jpg'], ['B.jpg', 'C.jpg']]
    copied, missing = module._BatchDirectory__create_batch_folders(
        str(out), zones, str(src), str(log))
    assert (copied, missing) == (4, 0)  # 2 per zone, shared file counted per zone

    # No image files land in the zones - the pool holds the pixels.
    assert not list((out / 'zone_1').rglob('*.jpg'))

    z1_list = (out / 'zone_1' / 'zone_1.imagelist').read_text().split()
    z2_list = (out / 'zone_2' / 'zone_2.imagelist').read_text().split()
    assert all(os.path.isabs(p) and os.path.isfile(p) for p in z1_list)

    z1_rows = (out / 'zone_1' / 'flight_log_UTM.txt').read_text().splitlines()
    z2_rows = (out / 'zone_2' / 'flight_log_UTM.txt').read_text().splitlines()
    z1_files = [r.split(';')[0] for r in z1_rows[1:]]
    z2_files = [r.split(';')[0] for r in z2_rows[1:]]
    assert all(os.path.isabs(f) for f in z1_files)

    # THE point of pool layout: the overlap image resolves to the SAME
    # canonical path in both zones' lists AND both zones' flight logs.
    b_paths = ({p for p in z1_list if p.endswith('B.jpg')} |
               {p for p in z2_list if p.endswith('B.jpg')} |
               {f for f in z1_files if f.endswith('B.jpg')} |
               {f for f in z2_files if f.endswith('B.jpg')})
    assert len(b_paths) == 1


def test_pool_counts_and_drops_missing_rows(tmp_path):
    src = _source(tmp_path, ['A.jpg'])
    log = _write_log(tmp_path / 'master.txt', ['A.jpg', 'GONE.jpg'])
    out = tmp_path / 'batched'
    out.mkdir()
    module = _module('pool')
    copied, missing = module._BatchDirectory__create_batch_folders(
        str(out), [['A.jpg', 'GONE.jpg']], str(src), str(log))
    assert (copied, missing) == (1, 1)
    rows = (out / 'zone_1' / 'flight_log_UTM.txt').read_text().splitlines()
    # The absent image's row must NOT survive into the zone log - a row
    # naming a missing image fails the RS import (err:18002).
    assert len(rows) == 2 and rows[1].split(';')[0].endswith('A.jpg')


def test_pool_warns_and_skips_xmp_priors(tmp_path, caplog):
    """Pool + XMP priors WARNS and continues; it must never kill the run.

    Behaviour change 2026-09-06. This used to raise ValueError, which run()
    catches into {'Success': False} and main.py turns into sys.exit(1). That
    was defensible while batch_xmp_priors defaulted to False - an operator who
    typed the flag got told it was incompatible. It became indefensible the
    moment the flag became a DEFAULT (owner directive): every pool run would
    have died before writing a single zone, over a default nobody chose.

    The incompatibility itself is real and unchanged - pool zones hold only an
    .imagelist, so the only place a sidecar could go is beside the canonical
    source image, and that tree is read-only (hard rule 0). Skipping is the
    right resolution; the obligation is to say so, which is what is pinned
    here. Calibration priors still reach the solve via prior_groups.py.
    """
    src = _source(tmp_path, ['A.jpg'])
    out = tmp_path / 'batched'
    out.mkdir()
    module = _module('pool')
    module.params['batch_xmp_priors'].set_value(True)

    with caplog.at_level(logging.WARNING):
        copied, missing = module._BatchDirectory__create_batch_folders(
            str(out), [['A.jpg']], str(src), None)

    # The zone was still produced.
    assert (copied, missing) == (1, 0)
    assert (out / 'zone_1' / 'zone_1.imagelist').is_file()
    # No sidecar was written anywhere - not into the zone, not into the source.
    assert not list(out.rglob('*.xmp'))
    assert not list(Path(src).rglob('*.xmp'))
    # And the skip was announced, naming both the cause and the alternative.
    warning = '\n'.join(r.message for r in caplog.records
                        if r.levelno >= logging.WARNING)
    assert 'batch_xmp_priors' in warning
    assert 'POOL' in warning
    assert 'prior_groups' in warning


def test_copy_mode_refuses_fullpath_master(tmp_path):
    names = ['A.jpg']
    src = _source(tmp_path, names)
    abs_name = str((src / 'A.jpg').resolve())
    log = _write_log(tmp_path / 'master.txt', [abs_name])
    out = tmp_path / 'batched'
    out.mkdir()
    module = _module()  # default copy layout
    with pytest.raises(ValueError, match='absolute image paths'):
        module._BatchDirectory__create_batch_folders(
            str(out), [[abs_name]], str(src), str(log))


def test_default_layout_is_copy_and_unchanged(tmp_path):
    # The default also requires native calibration. Use registered cameras so
    # this positive layout fixture represents a valid default batch.
    names = ['cammid_001.jpg', 'camupper_001.jpg']
    src = _source(tmp_path, names)
    log = _write_log(tmp_path / 'master.txt', names)
    out = tmp_path / 'batched'
    out.mkdir()
    module = _module()
    assert module.params['batch_xmp_priors'].get_value() is True
    copied, missing = module._BatchDirectory__create_batch_folders(
        str(out), [names], str(src), str(log))
    assert (copied, missing) == (2, 0)
    # Legacy behaviour intact: physical copies, basename log rows.
    assert sorted(p.name for p in (out / 'zone_1').rglob('*.jpg')) == names
    rows = (out / 'zone_1' / 'flight_log_UTM.txt').read_text().splitlines()
    assert rows[1].split(';')[0] == names[0]
    assert len(list((out / 'zone_1').rglob('*.xmp'))) == len(names)
    for image in (out / 'zone_1').rglob('*.jpg'):
        camera_registry.validate_calibration_xmp(
            image.with_suffix('.xmp').read_text(encoding='utf-8'), camera_registry.identify(image.name))
    assert not list(src.rglob('*.xmp'))


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
