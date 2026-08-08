#!/usr/bin/env python3
"""The portal's generated command must actually RUN.

WildScan builds one main.py invocation for the enabled chain. main.py
builds its argparse from the ENABLED modules only and rejects unknown
flags with exit 2 - and build_commands forwarded the WHOLE persisted
answer set plus the five forced model flags, unconditionally.

Measured (audit 2026-08-07): 16 of 31 stage selections rejected on a first
session, 29 of 31 once rs_settings.json carried a previous full run's
answers. default_enabled() deliberately unticks completed stages, so the
SECOND session always landed in the broken region. The six existing
build_commands tests all assert on the argv STRING and never execute it,
and every one of them includes 'align'.

This file feeds the generated argv to main.py's OWN parser
(main.build_arg_parser over main.initialize_parameters for the same
RS_MODULES set) for all 31 selections, in both states - plus one real
subprocess to prove the parser under test is the one the process uses. It
is the test the old ones were not.

Also here: the required data-type question, the publish CRS, and the
camera records the wizard collects as REQUIRED answers and then drops.

No RealityScan and no pipeline work. wildscan.session imports cleanly
without textual (only the TUI needs it), so these run everywhere.

Run:  py -3.13 -m pytest testing/test_wildscan_commands_runnable.py
"""
from __future__ import annotations

import itertools
import json
import logging
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO_ROOT)

import main as main_mod  # noqa: E402
import wildscan.session as session_mod  # noqa: E402
from wildscan.session import (CHAIN_STAGES, MODULE_DISPLAY, Question,  # noqa: E402
                              Session, build_commands, build_questions,
                              chain_arg_names, scan_raw_data,
                              workspace_input_crs, write_camera_records)
from wildscan.workspace import Workspace  # noqa: E402


class FakeStore:
    def __init__(self):
        self.data = {}

    def get(self, section, key, fallback=None):
        return self.data.get(section, {}).get(key, fallback)

    def set(self, section, key, value):
        self.data.setdefault(section, {})[key] = value


@pytest.fixture(autouse=True)
def store(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(session_mod, "_settings", lambda: fake)
    return fake


# A full previous run's answers - what load_last_run() hands the next
# session, and the state that broke 29 of 31 selections.
FULL_ANSWERS = {
    "i_input": "D:/cruise/dive.mov",
    "i_output_fpm": "60",
    "g_input": "D:/ws/raw_images",
    "g_flight_log": "D:/cruise/nav.csv",
    "g_type": "All",
    "g_declination": "0.0",
    "p_input": "D:/ws/raw_images",
    "b_input": "D:/ws/preprocessed_images",
    "b_target_images": "3000",
    "r_input": "D:/ws/batched_images_by_zone",
    "r_project_label": "NA167_H2075",
    "cam_vn_name": "Voyis New",
    "cam_vn_lever": "1.0/0.0/1.0",
    "cam_vn_tilt": "30",
}

ALL_SELECTIONS = [list(combo)
                  for size in range(1, len(CHAIN_STAGES) + 1)
                  for combo in itertools.combinations(CHAIN_STAGES, size)]


def _chain_command(session):
    for cmd in build_commands(session):
        if str(cmd.argv[1]).endswith('main.py'):
            return cmd
    return None


_QUIET = logging.getLogger('wildscan-argv-test')
_QUIET.addHandler(logging.NullHandler())
_QUIET.propagate = False


def _parser_for(chain):
    """main.py's real parser for this RS_MODULES selection."""
    modules = {MODULE_DISPLAY[k]: session_mod._module_registry()[k]
               for k in chain}
    return main_mod.build_arg_parser(main_mod.initialize_parameters(modules))


def _parse_or_fail(cmd, chain, label):
    """Feed the generated argv to main.py's parser exactly as the process
    does. argparse calls sys.exit(2) on an unknown flag."""
    parser = _parser_for(chain)
    try:
        parser.parse_args(cmd.argv[2:])       # drop [python, main.py]
    except SystemExit as exc:
        pytest.fail(f'selection {chain} ({label} answers) was REJECTED by '
                    f"main.py's own parser (exit {exc.code}); argv: "
                    f'{" ".join(cmd.argv[2:])}')


@pytest.mark.parametrize('enabled', ALL_SELECTIONS,
                         ids=['+'.join(s) for s in ALL_SELECTIONS])
def test_every_stage_selection_produces_accepted_arguments(enabled, tmp_path):
    """Fresh session AND resumed session, all 31 chain selections."""
    for label, answers in (('no', {}), ('full', dict(FULL_ANSWERS))):
        session = Session(expedition='NA167', dive='H2075',
                          results_root=str(tmp_path / 'ws'),
                          enabled=list(enabled), answers=dict(answers))
        cmd = _chain_command(session)
        assert cmd is not None
        _parse_or_fail(cmd, list(enabled), label)


def test_the_real_process_accepts_the_generated_argv(tmp_path):
    """One end-to-end subprocess, so the in-process parser above is proved
    to be the one main.py actually uses. The run is expected to FAIL in
    module validation (the workspace is empty) - what must never appear is
    argparse's 'unrecognized arguments'."""
    session = Session(expedition='NA167', dive='H2075',
                      results_root=str(tmp_path / 'ws'),
                      enabled=['georeference', 'preprocess', 'batch'],
                      answers=dict(FULL_ANSWERS))
    cmd = _chain_command(session)
    env = dict(os.environ)
    env.update(cmd.env)
    env['RS_NO_INTERACTIVE'] = '1'
    proc = subprocess.run(cmd.argv, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, cwd=REPO_ROOT, env=env,
                          timeout=600)
    combined = proc.stdout + proc.stderr
    assert 'unrecognized arguments' not in combined, combined[-500:]
    assert proc.returncode != 2, combined[-500:]


def test_forced_model_flags_only_ride_with_align(tmp_path):
    """The five --r_model_* / --r_display_output flags belong to
    RealityScan Alignment; appending them unconditionally alone rejected
    every align-less selection."""
    for enabled in (['georeference'], ['georeference', 'preprocess', 'batch'],
                    ['extract']):
        session = Session(results_root=str(tmp_path / 'ws'),
                          enabled=list(enabled), answers=dict(FULL_ANSWERS))
        argv = _chain_command(session).argv
        assert '--r_model_generate' not in argv, enabled
        assert '--r_display_output' not in argv, enabled
    session = Session(results_root=str(tmp_path / 'ws'),
                      enabled=['batch', 'align'], answers=dict(FULL_ANSWERS))
    argv = _chain_command(session).argv
    assert '--r_model_generate' in argv
    assert '--r_display_output' in argv


def test_answers_from_other_stages_are_kept_but_not_forwarded(tmp_path):
    """session.answers is the persisted superset by design - a resumed
    session keeps its defaults. The command line is what must be filtered."""
    session = Session(results_root=str(tmp_path / 'ws'),
                      enabled=['batch', 'align'], answers=dict(FULL_ANSWERS))
    argv = _chain_command(session).argv
    assert '--g_input' not in argv and '--p_input' not in argv
    assert session.answers['g_input'] == FULL_ANSWERS['g_input']


def test_disable_when_module_active_is_honoured_by_the_filter(tmp_path):
    """batch+align: Alignment's --r_input is disabled by Batch Directory,
    so main.py does not define it and the portal must not send it."""
    names = chain_arg_names(['batch', 'align'])
    assert 'r_input' not in names
    assert 'b_input' in names
    # ... and align alone DOES define it.
    assert 'r_input' in chain_arg_names(['align'])


@pytest.mark.parametrize('chain', ALL_SELECTIONS,
                         ids=['+'.join(s) for s in ALL_SELECTIONS])
def test_chain_arg_names_matches_main_pys_own_parameter_build(chain):
    """Same rule, not a parallel list: compare against main.py's
    initialize_parameters for every selection."""
    chain = list(chain)
    modules = {MODULE_DISPLAY[k]: session_mod._module_registry()[k]
               for k in chain}
    expected = {p.cli_long
                for p in main_mod.initialize_parameters(modules).values()}
    assert chain_arg_names(chain) == expected, chain


# ------------------------------------------------------ required data type

def test_geo_input_type_is_required_and_constrained(tmp_path):
    session = Session(results_root=str(tmp_path / 'ws'),
                      enabled=['georeference'])
    questions = {q.arg: q for q in build_questions(session,
                                                   scan_raw_data(tmp_path))}
    q = questions['g_type']
    assert q.required, 'a blank answer used to reach validate_parameters'
    assert q.validate('') == 'this one is required'
    assert q.validate('nonsense') is not None
    for good in ('All', 'wca', 'Zeuss', 'WCA2025'):
        assert q.validate(good) is None, good


def test_question_choices_do_not_affect_unconstrained_questions():
    assert Question('x', 'a', 'p', 'text').validate('anything') is None


# ---------------------------------------------------------- publish CRS

@pytest.mark.parametrize('tag,epsg', [
    # MGRS band letters: C..M are SOUTH of the equator, N..X north - so
    # '54S' is a NORTHERN zone (latitude band S = 32-40 N), which is
    # exactly the confusion the EPSG helper exists to remove.
    ('54S', 'EPSG:32654'),
    ('54L', 'EPSG:32754'),
    ('53N', 'EPSG:32653'),
])
def test_publish_carries_the_workspace_crs(tmp_path, tag, epsg):
    ws = tmp_path / 'ws'
    (ws / 'raw_images').mkdir(parents=True)
    (ws / 'raw_images' / f'flight_log_{tag}_UTM.txt').write_text(
        'filename;X (East);Y (North)\na.jpg;1;2\n', encoding='utf-8')
    (ws / 'exports').mkdir()
    assert workspace_input_crs(Workspace(ws)) == epsg
    session = Session(results_root=str(ws), enabled=['publish'])
    argv = build_commands(session)[0].argv
    assert '--input-crs' in argv
    assert argv[argv.index('--input-crs') + 1] == epsg


def test_publish_omits_the_crs_for_a_local_frame_campaign(tmp_path):
    ws = tmp_path / 'ws'
    (ws / 'raw_images').mkdir(parents=True)
    (ws / 'raw_images' / 'flight_log_UTM.txt').write_text(
        'filename;X (East);Y (North)\na.jpg;1;2\n', encoding='utf-8')
    assert workspace_input_crs(Workspace(ws)) is None
    session = Session(results_root=str(ws), enabled=['publish'])
    assert '--input-crs' not in build_commands(session)[0].argv


# ------------------------------------------------------- camera records

def test_collected_camera_answers_are_written_beside_the_results(tmp_path):
    """The wizard asks for a new camera's lever arm and tilt as REQUIRED
    answers and then drops every cam_* key from argv - by design. Leaving
    them only in rs_settings.json lost the measurement the operator just
    took."""
    ws = tmp_path / 'ws'
    session = Session(expedition='NA167', dive='H2075',
                      results_root=str(ws), enabled=['align'],
                      answers=dict(FULL_ANSWERS))
    path = write_camera_records(session)
    assert path is not None and path.name == 'camera_records.json'
    payload = json.loads(path.read_text(encoding='utf-8'))
    assert payload['cameras']['cam_vn_lever'] == '1.0/0.0/1.0'
    assert payload['cameras']['cam_vn_tilt'] == '30'
    assert payload['expedition'] == 'NA167'
    # It must say what it is NOT: these are records, not runtime settings.
    assert any('cameras.json' in line for line in payload['_comment'])


def test_no_camera_answers_writes_no_file(tmp_path):
    ws = tmp_path / 'ws'
    ws.mkdir()
    session = Session(results_root=str(ws), enabled=['align'],
                      answers={'g_type': 'All'})
    assert write_camera_records(session) is None
    assert not (ws / 'camera_records.json').exists()


# ------------------------------------------------- stale export resolution
# wildscan/app.py is the TUI and needs textual, which is not a test
# dependency - so the structural property is pinned by AST, the same
# no-real-tool philosophy the .bat guards use.

def _app_tree():
    import ast
    return ast.parse(open(os.path.join(REPO_ROOT, 'wildscan', 'app.py'),
                          encoding='utf-8').read())


def _function(tree, name, containing=None):
    """The FunctionDef called ``name``; when several exist (the TUI has one
    per screen), the one whose source contains ``containing``."""
    import ast
    matches = [n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == name]
    if containing is not None:
        matches = [n for n in matches if containing in ast.unparse(n)]
    return matches[0] if matches else None


def test_the_export_command_is_re_resolved_at_launch_time():
    """--project and --names were baked in at PLAN time (on_mount), before
    any stage ran, so a re-run that included Merge exported the PREVIOUS
    run's assembly under the new run's name."""
    import ast
    tree = _app_tree()
    refresh = _function(tree, '_refresh_export_command')
    assert refresh is not None, 'the launch-time re-resolution is gone'
    body = ast.unparse(refresh)
    assert 'export_names_file' in body
    assert 'assembly_project' in body
    assert "'--project'" in body and "'--names'" in body

    advance = _function(tree, '_advance', containing='self.runner.start')
    source = ast.unparse(advance)
    assert 'self._refresh_export_command()' in source, \
        '_advance no longer re-resolves before launching'
    # ... and it must happen BEFORE the runner starts the command.
    assert source.index('self._refresh_export_command()') < \
        source.index('self.runner.start')


def test_camera_records_are_written_when_the_run_starts():
    import ast
    on_mount = _function(_app_tree(), 'on_mount', containing='build_commands')
    assert on_mount is not None
    assert 'write_camera_records' in ast.unparse(on_mount)
