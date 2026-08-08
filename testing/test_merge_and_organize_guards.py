#!/usr/bin/env python3
"""Merge union log, merge exit codes, and the folder-organisation step.

merge_zones.build_union_flight_log (audit 2026-08-07):
  - the coordinate FRAME for the whole merge came from zone_logs[0] in
    os.walk order, while the ROWS were read in sorted() order. One
    untagged *_UTM.txt anywhere under images_root flipped the merge to
    FlightLogParamsLocal.xml on a logger.warning - the 2026-08-07 silent
    mis-frame class flight_logs._FRAME_INCIDENT exists to prevent.
  - when only_basenames matched nothing, a HEADER-ONLY union log was
    written and logged at INFO as '0 rows'; the workflow then imported it,
    ran -update against zero constraints, and shipped an UNGEOREFERENCED
    merged component with workflow_success true.

merge_zones.main:
  - --auto_model logged every model failure and still returned 0, so a run
    in which NO model was produced reported 'Merge stage complete'.
    run_models.py does the opposite for the same operation.
  - EVALUATION_READY.txt was written BEFORE the assembly result was
    checked: an on-disk document declaring a terminal state for a project
    that was never saved.

organize_by_date.py (step 1 of the owner's chain):
  - its date regex was anchored at the START of the name, so it matched
    only the Sony scheme. On rig imagery every file took the "no date
    pattern" branch and the script printed 'Complete: 0 files moved' and
    exited 0. Probed: 'P231C0001_20260807T120000Z.jpg' -> None,
    'camlower_20231104020854.jpg' -> None, 'ZEUSS_...' -> None.
  - it shipped a hardcoded per-user default path (hard rule 5).
  - shutil.move onto an existing FILE overwrites silently.

Offline: no RealityScan; merge_zones' union builder is called directly and
the exit-code contracts are checked as source structure.

Run:  py -3.13 -m pytest testing/test_merge_and_organize_guards.py
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO_ROOT)

import organize_by_date  # noqa: E402

QUIET = logging.getLogger('merge-test')
QUIET.addHandler(logging.NullHandler())
QUIET.propagate = False

HEADER = 'filename;X (East);Y (North);Alt'


def _zone_log(directory, name, images):
    directory.mkdir(parents=True, exist_ok=True)
    rows = [HEADER] + [f'{n};1;2;3' for n in images]
    (directory / name).write_text('\n'.join(rows) + '\n', encoding='utf-8')


def _merge_zones():
    pytest.importorskip('numpy')
    import merge_zones
    return merge_zones


# ------------------------------------------------------------- union frame

def test_a_stray_untagged_log_cannot_flip_the_whole_merge(tmp_path):
    """One untagged log under images_root flipped the entire merge to the
    LOCAL template - the silent mis-frame class, on a warning."""
    merge_zones = _merge_zones()
    images = tmp_path / 'batched'
    _zone_log(images / 'zone_1', 'flight_log_53N_UTM.txt', ['a.jpg'])
    _zone_log(images / 'zone_2', 'flight_log_UTM.txt', ['b.jpg'])
    out = tmp_path / 'merged'
    out.mkdir()
    with pytest.raises(ValueError) as exc:
        merge_zones.build_union_flight_log(str(images), str(out), QUIET)
    assert 'no zone tag' in str(exc.value)
    assert 'flight_log_UTM.txt' in str(exc.value)


def test_disagreeing_zones_are_refused(tmp_path):
    merge_zones = _merge_zones()
    images = tmp_path / 'batched'
    _zone_log(images / 'zone_1', 'flight_log_53N_UTM.txt', ['a.jpg'])
    _zone_log(images / 'zone_2', 'flight_log_57L_UTM.txt', ['b.jpg'])
    out = tmp_path / 'merged'
    out.mkdir()
    with pytest.raises(ValueError, match='DISAGREEING'):
        merge_zones.build_union_flight_log(str(images), str(out), QUIET)


def test_a_consistent_utm_merge_still_builds(tmp_path):
    merge_zones = _merge_zones()
    images = tmp_path / 'batched'
    _zone_log(images / 'zone_1', 'flight_log_53N_UTM.txt', ['a.jpg'])
    _zone_log(images / 'zone_2', 'flight_log_53N_UTM.txt', ['b.jpg'])
    out = tmp_path / 'merged'
    out.mkdir()
    union, params = merge_zones.build_union_flight_log(
        str(images), str(out), QUIET)
    assert os.path.basename(union) == 'flight_log_53N_UTM.txt'
    assert 'epsg:32653' in open(params, encoding='utf-8').read()
    assert len(open(union, encoding='utf-8').read().splitlines()) == 3


def test_a_consistent_local_merge_still_builds(tmp_path):
    """The genuine local-frame campaign (ON2026 COLMAP priors) must still
    work - the guard is about DISAGREEMENT, not about local frames."""
    merge_zones = _merge_zones()
    images = tmp_path / 'batched'
    _zone_log(images / 'zone_1', 'flight_log_UTM.txt', ['a.jpg'])
    _zone_log(images / 'zone_2', 'flight_log_UTM.txt', ['b.jpg'])
    out = tmp_path / 'merged'
    out.mkdir()
    union, params = merge_zones.build_union_flight_log(
        str(images), str(out), QUIET)
    assert '_local_UTM.txt' in os.path.basename(union)
    assert '+proj=geocent' in open(params, encoding='utf-8').read()


def test_a_zero_row_union_log_is_refused(tmp_path):
    """It used to be written, imported, and -update'd against zero
    constraints - an ungeoreferenced merged component with
    workflow_success true."""
    merge_zones = _merge_zones()
    images = tmp_path / 'batched'
    _zone_log(images / 'zone_1', 'flight_log_53N_UTM.txt', ['a.jpg'])
    out = tmp_path / 'merged'
    out.mkdir()
    with pytest.raises(ValueError) as exc:
        merge_zones.build_union_flight_log(
            str(images), str(out), QUIET,
            only_basenames={'nothing_matches.jpg'})
    assert 'ZERO rows' in str(exc.value)
    assert not list(out.glob('flight_log*')), 'a useless log was written'


def test_the_frame_decision_uses_a_sorted_list():
    """The frame came from zone_logs[0] in os.walk order while the rows
    were read sorted() - two different orders over the same list."""
    source = open(os.path.join(REPO_ROOT, 'merge_zones.py'),
                  encoding='utf-8').read()
    body = source[source.index('def build_union_flight_log'):
                  source.index('def build_union_flight_log') + 4000]
    assert 'zone_logs = sorted(zone_logs)' in body
    assert 'assert_one_zone(zone_logs' in body
    assert 'for log_path in sorted(zone_logs)' not in body


# ------------------------------------------------------- merge exit codes

def test_auto_model_failures_fail_the_run():
    """run_models.py stops on the first model failure 'so evidence
    survives'; this loop logged every failure and returned 0."""
    source = open(os.path.join(REPO_ROOT, 'merge_zones.py'),
                  encoding='utf-8').read()
    assert 'model_failures = []' in source
    assert 'model_failures.append(comp_name)' in source
    tail = source[source.index('if model_failures:'):]
    assert tail.split('return')[1].strip().startswith('1')


def test_the_evaluation_gate_is_written_only_on_success():
    """EVALUATION_READY.txt names a project whose existence was never
    checked, and the census reads its presence as merge status 'done'."""
    source = open(os.path.join(REPO_ROOT, 'merge_zones.py'),
                  encoding='utf-8').read()
    failure_return = source.index("logger.error('Assembly workflow failed")
    gate_write = source.index("eval_path = os.path.join(output_dir, "
                              "'EVALUATION_READY.txt')")
    assert failure_return < gate_write, \
        'the gate is still written before the assembly result is checked'
    assert 'EVALUATION_BLOCKED.txt' in source


# ---------------------------------------------------------- organize_by_date

@pytest.mark.parametrize('name', [
    'P231C0001_20260807T120000Z.jpg',      # WCA
    'camlower_20231104020854.jpg',         # legacy rig
    'ZEUSS_20260807T120000Z.jpg',          # Zeuss
    '20250729T155918__DSC7725_ILCE-1.jpg',  # Sony (the only one that worked)
])
def test_every_rig_filename_family_is_dated(name):
    assert organize_by_date.extract_date_from_filename(name) is not None, name


def test_an_undateable_name_is_still_None():
    assert organize_by_date.extract_date_from_filename('IMG_0001.jpg') is None


def test_files_are_sorted_into_date_folders(tmp_path):
    (tmp_path / 'P231C0001_20260807T120000Z.jpg').write_bytes(b'j')
    (tmp_path / 'camlower_20231104020854.jpg').write_bytes(b'j')
    assert organize_by_date.organize_images_by_date(str(tmp_path)) == 0
    assert (tmp_path / '07August' /
            'P231C0001_20260807T120000Z.jpg').is_file()
    assert (tmp_path / '04November' / 'camlower_20231104020854.jpg').is_file()


def test_moving_nothing_is_a_LOUD_failure(tmp_path):
    """'Complete: 0 files moved' + exit 0 reads identically whether the
    folder was already organised, held no imagery, or holds imagery this
    script cannot date."""
    (tmp_path / 'IMG_0001.jpg').write_bytes(b'j')
    assert organize_by_date.organize_images_by_date(str(tmp_path)) == 1


def test_an_imageless_folder_is_a_LOUD_failure(tmp_path):
    assert organize_by_date.organize_images_by_date(str(tmp_path)) == 1


def test_an_existing_destination_file_is_skipped_not_overwritten(tmp_path):
    """shutil.move's collision check only fires when the destination is a
    DIRECTORY, so a same-named file was silently replaced."""
    name = 'P231C0001_20260807T120000Z.jpg'
    (tmp_path / name).write_bytes(b'NEW')
    target = tmp_path / '07August'
    target.mkdir()
    (target / name).write_bytes(b'ORIGINAL')
    organize_by_date.organize_images_by_date(str(tmp_path))
    assert (target / name).read_bytes() == b'ORIGINAL'
    assert (tmp_path / name).read_bytes() == b'NEW', 'the source was consumed'


def test_dry_run_moves_nothing(tmp_path):
    name = 'P231C0001_20260807T120000Z.jpg'
    (tmp_path / name).write_bytes(b'j')
    assert organize_by_date.organize_images_by_date(str(tmp_path),
                                                    dry_run=True) == 0
    assert (tmp_path / name).is_file()
    assert not (tmp_path / '07August').exists()


def test_no_hardcoded_per_user_path_remains():
    """hard rule 5: data lives on volumes with user-specific paths."""
    source = open(os.path.join(REPO_ROOT, 'organize_by_date.py'),
                  encoding='utf-8').read()
    assert not re.search(r"r?['\"][A-Z]:\\\\?[A-Za-z]", source), \
        'a hardcoded drive-letter default is back'


def test_organize_runs_unattended():
    proc = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, 'organize_by_date.py'),
         '--help'],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
        cwd=REPO_ROOT)
    assert proc.returncode == 0 and 'Traceback' not in proc.stderr
    assert '--dry-run' in proc.stdout and '--source' in proc.stdout
