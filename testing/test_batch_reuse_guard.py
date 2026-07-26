#!/usr/bin/env python3
"""Unit tests for the Batch Directory reuse guard (batch_inputs.json).

Regression cover for two near-misses on 2026-07-26:

1. The zone folders silently held a BLEND of two zonings - 12,679 images on
   disk against 9,834 reported - because a changed flight log was allowed to
   reuse an existing tree, and `__copy_files` skips destinations by name so it
   can never remove a member the new zoning dropped.
2. The first version of the guard fingerprinted only the flight log and the
   zoning parameters, so a run that ADDED preprocessing produced a
   byte-identical fingerprint. `__get_input_dir` switches to
   preprocessed_images once that folder exists, preprocess writes the same
   filenames, every copy is skipped, and the zones keep RAW pixels.
   It also failed OPEN on a missing or unreadable marker - which was exactly
   the interrupted-copy case it was written for, since the marker used to be
   written only after all copying finished.

No RealityScan, no batching: the guard is exercised directly.

Run:  py -3.13 -m pytest testing/test_batch_reuse_guard.py
"""

from __future__ import annotations

import json
import logging
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO_ROOT)

from modules.image_batcher.batch_directory import BatchDirectory  # noqa: E402
from module_base.parameter import Parameter  # noqa: E402


def _module(tmp_path, input_dir):
    """A BatchDirectory with just enough parameter state for the guard.

    `output_dir` is a GLOBAL parameter injected by main.initialize_parameters,
    not by the module, so it is constructed here the same way.
    """
    mod = BatchDirectory(logging.getLogger('test'))
    mod.params = mod.get_parameters()
    mod.params['output_dir'] = Parameter(
        name='Output Directory', cli_short='o', cli_long='output_dir',
        type=str, default_value=None, description='Path to the output directory')
    mod.params['output_dir'].set_value(str(tmp_path))
    mod.params['batch_input_image_dir'].set_value(str(input_dir))
    for key, value in (('batch_target_images_per_zone', 2000),
                       ('batch_min_zone_size', 100),
                       ('batch_max_zone_size', 4000),
                       ('batch_initial_overlap_percent', 20.0),
                       ('batch_density_weight', 0.3),
                       ('batch_kde_bandwidth', 0.0)):
        mod.params[key].set_value(value)
    return mod


def _images(directory, names, payload=b'\xff\xd8fake-jpeg'):
    directory.mkdir(parents=True, exist_ok=True)
    for n in names:
        (directory / n).write_bytes(payload)
    return directory


def _flight_log(path, rows=3):
    lines = ['filename;X (East);Y (North);Alt']
    lines += [f'img_{i}.jpg;1.0;2.0;-100.0' for i in range(rows)]
    path.write_text('\n'.join(lines), encoding='utf-8')
    return path


def _zone_tree(tmp_path, names):
    """A batched output tree that already holds images."""
    out = tmp_path / 'batched_images_by_zone'
    _images(out / 'zone_1', names)
    return out


# --------------------------------------------------------------- fingerprint

def test_fingerprint_includes_input_dir_and_signature(tmp_path):
    raw = _images(tmp_path / 'raw_images', ['a.jpg', 'b.jpg'])
    log = _flight_log(tmp_path / 'flight_log_4Q_UTM.txt')
    fp = _module(tmp_path, raw)._input_fingerprint(str(log))

    assert fp['input_dir'] is not None, 'the image source must be fingerprinted'
    assert fp['input_signature']['images'] == 2
    assert fp['input_signature']['bytes'] > 0
    assert fp['flight_log_sha256']


def test_raw_vs_preprocessed_swap_is_detected(tmp_path):
    """Same filenames, same flight log, DIFFERENT pixels -> different print."""
    names = ['a.jpg', 'b.jpg']
    log = _flight_log(tmp_path / 'flight_log_4Q_UTM.txt')
    raw = _images(tmp_path / 'raw_images', names, payload=b'\xff\xd8raw')
    pre = _images(tmp_path / 'preprocessed_images', names,
                  payload=b'\xff\xd8clahe-processed-larger')

    raw_fp = _module(tmp_path, raw)._input_fingerprint(str(log))
    pre_fp = _module(tmp_path, pre)._input_fingerprint(str(log))

    assert raw_fp != pre_fp, 'a raw/preprocessed swap must change the fingerprint'
    assert raw_fp['input_dir'] != pre_fp['input_dir']


# --------------------------------------------------------------- reuse guard

def test_reuse_allowed_when_inputs_unchanged(tmp_path):
    raw = _images(tmp_path / 'raw_images', ['a.jpg'])
    log = _flight_log(tmp_path / 'flight_log_4Q_UTM.txt')
    mod = _module(tmp_path, raw)
    out = _zone_tree(tmp_path, ['a.jpg'])
    mod._write_fingerprint(str(out), str(log), status='complete')

    ok, msg = mod._check_reuse_is_safe(str(out), str(log))
    assert ok, msg


def test_reuse_refused_when_flight_log_changed(tmp_path):
    raw = _images(tmp_path / 'raw_images', ['a.jpg'])
    log = _flight_log(tmp_path / 'flight_log_4Q_UTM.txt')
    mod = _module(tmp_path, raw)
    out = _zone_tree(tmp_path, ['a.jpg'])
    mod._write_fingerprint(str(out), str(log), status='complete')

    _flight_log(log, rows=9)          # the lever-arm-fix scenario
    ok, msg = mod._check_reuse_is_safe(str(out), str(log))
    assert not ok
    assert 'flight_log_sha256' in msg


def test_reuse_refused_when_image_source_changed(tmp_path):
    """The M2 regression: identical log+params, different pixel source."""
    names = ['a.jpg']
    log = _flight_log(tmp_path / 'flight_log_4Q_UTM.txt')
    raw = _images(tmp_path / 'raw_images', names, payload=b'\xff\xd8raw')
    out = _zone_tree(tmp_path, names)
    _module(tmp_path, raw)._write_fingerprint(str(out), str(log), status='complete')

    pre = _images(tmp_path / 'preprocessed_images', names,
                  payload=b'\xff\xd8clahe-processed')
    ok, msg = _module(tmp_path, pre)._check_reuse_is_safe(str(out), str(log))
    assert not ok, 'reusing zones built from raw pixels for a CLAHE run'
    assert 'input_dir' in msg or 'input_signature' in msg


def test_reuse_refused_when_marker_missing_but_zones_populated(tmp_path):
    """Interrupted copy: images present, no marker. Must FAIL CLOSED."""
    raw = _images(tmp_path / 'raw_images', ['a.jpg'])
    log = _flight_log(tmp_path / 'flight_log_4Q_UTM.txt')
    out = _zone_tree(tmp_path, ['a.jpg'])          # populated, no fingerprint

    ok, msg = _module(tmp_path, raw)._check_reuse_is_safe(str(out), str(log))
    assert not ok, 'a populated tree with no marker has unknown provenance'
    assert 'no' in msg.lower()


def test_reuse_refused_when_marker_unreadable(tmp_path):
    raw = _images(tmp_path / 'raw_images', ['a.jpg'])
    log = _flight_log(tmp_path / 'flight_log_4Q_UTM.txt')
    out = _zone_tree(tmp_path, ['a.jpg'])
    (out / BatchDirectory.FINGERPRINT_NAME).write_text('{not json', encoding='utf-8')

    ok, msg = _module(tmp_path, raw)._check_reuse_is_safe(str(out), str(log))
    assert not ok
    assert 'unreadable' in msg.lower()


def test_reuse_refused_when_previous_run_was_interrupted(tmp_path):
    """status=in_progress means the copy never finished."""
    raw = _images(tmp_path / 'raw_images', ['a.jpg'])
    log = _flight_log(tmp_path / 'flight_log_4Q_UTM.txt')
    mod = _module(tmp_path, raw)
    out = _zone_tree(tmp_path, ['a.jpg'])
    mod._write_fingerprint(str(out), str(log), status='in_progress')

    ok, msg = mod._check_reuse_is_safe(str(out), str(log))
    assert not ok
    assert 'mid-build' in msg or 'in_progress' in msg


def test_empty_zone_tree_is_reusable(tmp_path):
    """A fresh/empty output dir is not a provenance problem."""
    raw = _images(tmp_path / 'raw_images', ['a.jpg'])
    log = _flight_log(tmp_path / 'flight_log_4Q_UTM.txt')
    out = tmp_path / 'batched_images_by_zone'
    out.mkdir()

    ok, msg = _module(tmp_path, raw)._check_reuse_is_safe(str(out), str(log))
    assert ok, msg


def test_status_is_not_compared_as_an_input(tmp_path):
    """A complete marker must not be refused merely because status differs."""
    raw = _images(tmp_path / 'raw_images', ['a.jpg'])
    log = _flight_log(tmp_path / 'flight_log_4Q_UTM.txt')
    mod = _module(tmp_path, raw)
    out = _zone_tree(tmp_path, ['a.jpg'])
    mod._write_fingerprint(str(out), str(log), status='complete')

    stored = json.loads((out / BatchDirectory.FINGERPRINT_NAME).read_text(encoding='utf-8'))
    assert stored['status'] == 'complete'
    ok, _ = mod._check_reuse_is_safe(str(out), str(log))
    assert ok


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
