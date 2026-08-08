#!/usr/bin/env python3
"""Batch Directory: report what LANDED, not what was planned.

The batcher's summary was built from the ZONE LISTS, never from the copy.
A flight-log filename that matched nothing on disk emitted one warning and
`continue`d, so a whole-dive mismatch - extension CASE being the commonest
on Windows - created zone folders holding ZERO images, reported
Success=True with a plausible 'Total Images in Batches', wrote the
'complete' fingerprint (which then blessed the empty tree for reuse) and
handed empty folders to alignment (audit 2026-08-07).

Also here:
  - a flight log whose name column is neither 'filename' nor 'Name' blew
    up as a raw `KeyError: 'filename'` from inside __create_geographic_zones,
    OUTSIDE run()'s try/except, i.e. an unhandled traceback out of main.py
  - rs_settings.json's 'batch' section beat the command line: with the
    stored min_zone_size=300 and --b_min 2000, the batcher zoned at 300 -
    and both keys feed the provenance fingerprint

Offline: no RealityScan, no plotting (the zone maths is bypassed - these
tests exercise the copy accounting and the log parser directly).

Run:  py -3.13 -m pytest testing/test_batch_copy_accounting.py
"""
from __future__ import annotations

import logging
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO_ROOT)

pytest.importorskip('pandas')
pytest.importorskip('geopandas')

from module_base.parameter import Parameter  # noqa: E402
from modules.image_batcher.batch_directory import BatchDirectory  # noqa: E402

QUIET = logging.getLogger('batch-test')
QUIET.addHandler(logging.NullHandler())
QUIET.propagate = False

HEADER = ('filename;X (East);Y (North);Alt;X Accuracy;Y Accuracy;'
          'Alt Accuracy;Yaw;Pitch;Roll;Yaw Accuracy;Pitch Accuracy;'
          'Roll Accuracy')


class FakeStore:
    def __init__(self, data=None):
        self.data = data or {}

    def get(self, section, key, fallback=None):
        return self.data.get(section, {}).get(key, fallback)

    def set(self, section, key, value):
        self.data.setdefault(section, {})[key] = value


def _module(store=None):
    module = BatchDirectory(QUIET)
    module.settings = store or FakeStore()
    return module


def _log(path, names):
    rows = [HEADER]
    for i, name in enumerate(names):
        rows.append(f'{name};{100 + i};{200 + i};-5;10;10;1;90;45;0;15;15;15')
    path.write_text('\n'.join(rows) + '\n', encoding='utf-8')
    return path


# ------------------------------------------------------- copy accounting

def test_a_whole_dive_mismatch_copies_nothing_and_says_so(tmp_path):
    """Extension CASE: the log says .JPG, the disk says .jpg. Windows
    filesystems are case-insensitive, so this is a pure lookup bug - but
    it produced empty zones that reported success."""
    source = tmp_path / 'src'
    source.mkdir()
    for i in range(3):
        (source / f'C231C000{i}.jpg').write_bytes(b'j')

    module = _module()
    zones = [['C231C0000.JPG', 'C231C0001.JPG'], ['C231C0002.JPG']]
    out = tmp_path / 'batched'
    out.mkdir()
    copied, missing = module._BatchDirectory__create_batch_folders(
        str(out), zones, str(source), None)
    # Case-insensitive index: the commonest cause simply disappears.
    assert copied == 3 and missing == 0
    # The copy keeps the FLIGHT LOG's spelling (unchanged behaviour), so
    # the per-zone log and the file on disk stay identical strings.
    assert sorted(p.name for p in (out / 'zone_1').rglob('*.JPG')) == \
        ['C231C0000.JPG', 'C231C0001.JPG']
    assert sorted(p.name for p in (out / 'zone_2').rglob('*.JPG')) == \
        ['C231C0002.JPG']


def test_genuinely_absent_files_are_counted_not_just_warned(tmp_path):
    source = tmp_path / 'src'
    source.mkdir()
    (source / 'C231C0000.jpg').write_bytes(b'j')

    module = _module()
    out = tmp_path / 'batched'
    out.mkdir()
    copied, missing = module._BatchDirectory__create_batch_folders(
        str(out), [['C231C0000.jpg', 'GONE_A.jpg', 'GONE_B.jpg']],
        str(source), None)
    assert copied == 1
    assert missing == 2
    assert module._missing_example in ('GONE_A.jpg', 'GONE_B.jpg')


def test_copy_files_returns_its_tally(tmp_path):
    """__copy_files used to return None and aggregate nothing, which is
    why the caller had no number to gate on."""
    source = tmp_path / 'src'
    source.mkdir()
    (source / 'a.jpg').write_bytes(b'j')
    module = _module()
    dest = tmp_path / 'zone_1'
    dest.mkdir()
    assert module._BatchDirectory__copy_files(
        str(source), str(dest), ['a.jpg', 'b.jpg']) == (1, 1)


def test_unbatchable_formats_are_reported(tmp_path):
    """A .tif is recognised imagery elsewhere in the pipeline; leaving it
    behind silently is what made the census and the batcher disagree."""
    source = tmp_path / 'src'
    source.mkdir()
    (source / 'a.jpg').write_bytes(b'j')
    (source / 'b.tif').write_bytes(b't')

    messages = []

    class Cap(logging.Handler):
        def emit(self, record):
            messages.append(record.getMessage())

    logger = logging.getLogger('batch-format-test')
    logger.propagate = False
    logger.setLevel(logging.WARNING)
    logger.addHandler(Cap())
    module = BatchDirectory(logger)
    module.settings = FakeStore()
    out = tmp_path / 'batched'
    out.mkdir()
    module._BatchDirectory__create_batch_folders(
        str(out), [['a.jpg']], str(source), None)
    assert any('.tif' in m and 'NOT batched' in m for m in messages), messages


# ---------------------------------------- run() gates on what was copied

def _run_with_stubbed_zoning(tmp_path, monkeypatch, copied, missing,
                             planned=3):
    """BatchDirectory.run() with the heavy zoning/plotting stubbed, so the
    COPY-OUTCOME gate is what the test exercises."""
    import pandas as pd

    module = _module()
    out_root = tmp_path / 'ws'
    out_root.mkdir()
    params = {'output_dir': Parameter('output_dir', None, 'output_dir', str,
                                      None, prompt_user=False)}
    params['output_dir'].set_value(str(out_root))
    for name, value in (('batch_target_images_per_zone', 3000),
                        ('batch_min_zone_size', 1000),
                        ('batch_max_zone_size', 5000),
                        ('batch_initial_overlap_percent', 0.0),
                        ('batch_density_weight', 0.0),
                        ('batch_kde_bandwidth', 0.0),
                        ('batch_overlap_max_distance_m', 0.0)):
        p = Parameter(name, None, name, type(value), value, prompt_user=False)
        p.set_value(value)
        params[name] = p
    module.params = params

    gdf = pd.DataFrame({'filename': [f'img_{i}.jpg' for i in range(planned)]})
    zones = [[f'img_{i}.jpg' for i in range(planned)]]

    monkeypatch.setattr(module, '_BatchDirectory__get_input_dir',
                        lambda: str(tmp_path / 'src'))
    monkeypatch.setattr(module, '_BatchDirectory__get_flight_log_path',
                        lambda: None)
    monkeypatch.setattr(module, '_BatchDirectory__read_flight_log_gdf',
                        lambda _p: gdf)
    monkeypatch.setattr(module, '_BatchDirectory__create_geographic_zones',
                        lambda *a, **k: (zones, zones, gdf))
    monkeypatch.setattr(module, '_BatchDirectory__plot_results',
                        lambda *a, **k: None)
    monkeypatch.setattr(module, '_BatchDirectory__create_batch_folders',
                        lambda *a, **k: (copied, missing))
    monkeypatch.setattr(module, '_prompt_int',
                        lambda key, msg, fallback, cli_value=None: fallback)
    fingerprints = []
    monkeypatch.setattr(module, '_write_fingerprint',
                        lambda out, log, status: fingerprints.append(status))

    def eof(*_a, **_k):
        raise EOFError
    monkeypatch.setattr('builtins.input', eof)
    return module.run(), fingerprints


def test_run_fails_when_nothing_was_copied(tmp_path, monkeypatch):
    """It reported Success=True with a plausible 'Total Images in
    Batches' and wrote the 'complete' fingerprint, which then blessed the
    empty tree for reuse."""
    result, fingerprints = _run_with_stubbed_zoning(
        tmp_path, monkeypatch, copied=0, missing=3)
    assert result['Success'] is False
    assert result['Images Copied'] == 0
    assert 'complete' not in fingerprints, fingerprints


def test_the_zero_copy_gate_stands_on_its_own(tmp_path, monkeypatch):
    """Exercises the copied==0 gate ALONE, below the majority-missing
    threshold, so neither guard can mask the other's absence."""
    result, fingerprints = _run_with_stubbed_zoning(
        tmp_path, monkeypatch, copied=0, missing=1, planned=10)
    assert result['Success'] is False
    assert 'complete' not in fingerprints


def test_run_fails_when_most_images_are_missing(tmp_path, monkeypatch):
    result, fingerprints = _run_with_stubbed_zoning(
        tmp_path, monkeypatch, copied=1, missing=2)
    assert result['Success'] is False
    assert 'complete' not in fingerprints


def test_run_succeeds_and_reports_the_real_count(tmp_path, monkeypatch):
    result, fingerprints = _run_with_stubbed_zoning(
        tmp_path, monkeypatch, copied=3, missing=0)
    assert result['Success'] is True
    assert result['Images Copied'] == 3
    assert result['Images Missing'] == 0
    assert fingerprints == ['in_progress', 'complete']


# ------------------------------------------------------- flight-log parser

def test_missing_name_column_is_an_error_not_a_KeyError(tmp_path):
    """The X/Y columns were validated; the NAME column was not, and the
    KeyError fired later, outside run()'s try/except."""
    path = _log(tmp_path / 'log.txt', ['a.jpg'])
    path.write_text(
        'image;X (East);Y (North)\na.jpg;1;2\n', encoding='utf-8')
    module = _module()
    module.params = {}
    assert module._BatchDirectory__read_flight_log_gdf(str(path)) is None


def test_a_good_log_still_parses(tmp_path):
    path = _log(tmp_path / 'flight_log_53N_UTM.txt',
                ['a.jpg', 'b.jpg', 'c.jpg'])
    module = _module()
    module.params = {}
    gdf = module._BatchDirectory__read_flight_log_gdf(str(path))
    assert gdf is not None and len(gdf) == 3
    assert 'filename' in gdf.columns


def test_a_Name_headed_log_still_parses(tmp_path):
    """geoall writes 'Name'; the georeference module writes 'filename'."""
    path = tmp_path / 'flight_log_53N_UTM.txt'
    path.write_text('Name;X (East);Y (North)\na.jpg;1;2\n', encoding='utf-8')
    module = _module()
    module.params = {}
    gdf = module._BatchDirectory__read_flight_log_gdf(str(path))
    assert gdf is not None and 'filename' in gdf.columns


# ------------------------------------------- CLI value beats stored value

def _int_param(default, value):
    p = Parameter('n', None, 'n', int, default, prompt_user=False)
    p.set_value(value)
    return p


@pytest.fixture
def unattended(monkeypatch):
    """An EOF stdin - the state every driver run has (the prompt is
    EOF-safe and takes its default)."""
    def eof(*_a, **_k):
        raise EOFError
    monkeypatch.setattr('builtins.input', eof)


def test_cli_zone_size_outranks_another_expeditions_stored_value(unattended):
    """Measured: stored batch.min_zone_size=300 (from NA173) against a CLI
    --b_min of 2000 -> the batcher used 300. Same fail-open that was
    closed for the merge driver, still open here."""
    store = FakeStore({'batch': {'min_zone_size': 300}})
    module = _module(store)
    module.params = {'batch_min_zone_size': _int_param(1000, 2000)}
    assert module._explicit_param('batch_min_zone_size') == 2000
    assert module._stored_default('min_zone_size', 1000, 2000) == 2000
    assert module._prompt_int('min_zone_size', 'Minimum zone size', 2000,
                              cli_value=2000) == 2000


def test_stored_value_still_wins_when_the_caller_said_nothing(unattended):
    """The convenience default must survive - it is only outranked by an
    EXPLICIT answer."""
    store = FakeStore({'batch': {'min_zone_size': 300}})
    module = _module(store)
    module.params = {'batch_min_zone_size': _int_param(1000, 1000)}
    assert module._explicit_param('batch_min_zone_size') is None
    assert module._stored_default('min_zone_size', 1000, None) == 300
    assert module._prompt_int('min_zone_size', 'Minimum zone size', 1000,
                              cli_value=None) == 300


def test_cli_float_also_outranks_the_stored_value(unattended):
    # Two stores: _prompt_* persists its answer, so one store cannot show
    # both halves of the precedence rule.
    with_cli = _module(FakeStore({'batch': {'overlap_percent': 5.0}}))
    assert with_cli._prompt_float('overlap_percent', 'Overlap', 5.0,
                                  0.0, 100.0, cli_value=20.0) == 20.0
    without = _module(FakeStore({'batch': {'overlap_percent': 5.0}}))
    assert without._prompt_float('overlap_percent', 'Overlap', 12.0,
                                 0.0, 100.0) == 5.0


def test_explicit_param_ignores_an_unset_parameter():
    module = _module()
    module.params = {}
    assert module._explicit_param('batch_min_zone_size') is None


# --------------------------------------------- mixed-zone flight-log refusal

class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def _module_with_input(image_dir):
    """The module wired the way the orchestrator wires it: its own declared
    parameters, plus the georeference stage's input dir (the chained case
    __get_flight_log_path branches on)."""
    module = BatchDirectory(QUIET)
    module.settings = FakeStore()
    params = module.get_parameters()
    # main.py drops the parameters a co-enabled module disables; this one
    # is disabled by Georeference Images, and its presence short-circuits
    # __get_flight_log_path before the discovery branch under test.
    assert 'Georeference Images' in str(
        params['batch_flight_log_path'].disable_when_module_active)
    params.pop('batch_flight_log_path')
    params['output_dir'] = Parameter('Out', 'o', 'output_dir', str,
                                     str(image_dir), prompt_user=False)
    params['geo_input_image_dir'] = Parameter('In', 'g_i', 'g_input', str,
                                              str(image_dir),
                                              prompt_user=False)
    for p in params.values():
        if p.get_value() is None:
            p.set_value(p.get_default_value())
    params['batch_input_image_dir'].set_value(str(image_dir))
    module.params = params
    return module


def test_disagreeing_zone_logs_are_an_error_line_not_a_traceback(tmp_path):
    """find_flight_log now RAISES on a directory whose logs name different
    UTM zones. __get_flight_log_path is called from validate_parameters,
    OUTSIDE run()'s try/except, so an uncaught ValueError there is an
    unhandled traceback out of main.py - the shape the KeyError fix in this
    same file exists to remove (audit-verification 2026-08-07: the catch
    shipped with no test)."""
    _log(tmp_path / 'flight_log_53N_UTM.txt', ['a.jpg'])
    _log(tmp_path / 'flight_log_57L_UTM.txt', ['b.jpg'])
    capture = _Capture()
    logger = logging.getLogger('batch-mixed-zone-test')
    logger.propagate = False
    logger.setLevel(logging.ERROR)
    logger.addHandler(capture)
    module = _module_with_input(tmp_path)
    module.logger = logger
    try:
        got = module._BatchDirectory__get_flight_log_path()
    finally:
        logger.removeHandler(capture)
    assert got is None, got
    assert any('DISAGREEING coordinate frames' in m
               for m in capture.messages), capture.messages
    # ... and validate_parameters turns that into a refusal, not a crash.
    ok, msg = module.validate_parameters()
    assert ok is False and 'flight log' in msg.lower(), msg


def test_a_single_zone_directory_is_still_found(tmp_path):
    _log(tmp_path / 'flight_log_53N_UTM.txt', ['a.jpg'])
    module = _module_with_input(tmp_path)
    got = module._BatchDirectory__get_flight_log_path()
    assert got and os.path.basename(got) == 'flight_log_53N_UTM.txt'
