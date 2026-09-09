#!/usr/bin/env python3
"""Modelling must say what it did NOT build, and why (2026-09-09).

WHY THIS EXISTS. run_models skips components for several reasons and, before
this, most of them left no durable trace:

  - `already modelled` logged one line and appended nothing, which is CORRECT
    (the success record carries forward from the prior report) but was
    indistinguishable from a component that was never a candidate;
  - `scale_gate` recorded the component but the log line named neither the
    camera count nor the measured scale;
  - both `break` paths - the disk floor and a modelling failure - abandoned
    the REST of the candidate list with no record at all. On a 70-component
    dive a failure at component 3 silently dropped 67, and the report looked
    like a clean run that simply had little to do.

A modelling run that covered a third of a dive has to be distinguishable from
one that covered all of it, without diffing two JSON files.

Run:  python -m pytest testing/test_model_skip_accounting.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run_models import summarise_models, summary_lines  # noqa: E402


def _final(name, cams):
    return (f'zone_1/{name}', {'key': f'zone_1/{name}', 'camera_count': cams})


def _model(name, cams, **kw):
    return dict(component=name, cameras=cams, **kw)


# ------------------------------------------------------------------ counting

def test_a_clean_run_accounts_for_every_camera():
    finals = [_final('c0', 100), _final('c1', 200)]
    models = [_model('c0', 100, success=True), _model('c1', 200, success=True)]
    s = summarise_models(models, finals)
    assert s['candidates'] == 2 and s['candidate_cameras'] == 300
    assert s['modelled'] == 2 and s['modelled_cameras'] == 300
    assert s['failed'] == 0 and s['skipped'] == {}


def test_scale_gated_cameras_are_counted_separately():
    finals = [_final('c0', 100), _final('c1', 900)]
    models = [_model('c0', 100, success=True),
              _model('c1', 900, skipped='scale_gate', scale=1.27)]
    s = summarise_models(models, finals)
    assert s['modelled_cameras'] == 100
    assert s['skipped']['scale_gate'] == {'components': 1, 'cameras': 900}
    # The headline number is the one that matters: 10% of the dive was built.
    assert 100.0 * s['modelled_cameras'] / s['candidate_cameras'] == 10.0


def test_a_skipped_record_is_not_counted_as_failed():
    """A component that was never attempted did not FAIL. Conflating the two
    turns 'we refused to build it' into 'it broke', which sends the next
    person debugging the modeller instead of the scale."""
    finals = [_final('c0', 50)]
    models = [_model('c0', 50, success=False, skipped='scale_gate')]
    s = summarise_models(models, finals)
    assert s['failed'] == 0
    assert s['skipped']['scale_gate']['components'] == 1


def test_a_real_failure_is_counted_as_failed():
    finals = [_final('c0', 50)]
    models = [_model('c0', 50, success=False, errors='boom')]
    s = summarise_models(models, finals)
    assert s['failed'] == 1 and s['failed_cameras'] == 50


# --------------------------------------------------------------- not reached

def test_components_never_reached_are_visible_in_the_totals():
    """The defect this file exists for. Three candidates, a failure on the
    second, and the third never considered."""
    finals = [_final('c0', 10), _final('c1', 20), _final('c2', 5000)]
    models = [_model('c0', 10, success=True),
              _model('c1', 20, success=False, errors='boom'),
              _model('c2', 5000, skipped='not_reached',
                     why='stopped after c1 failed to model')]
    s = summarise_models(models, finals, stop_reason='stopped after c1 failed to model')
    assert s['skipped']['not_reached'] == {'components': 1, 'cameras': 5000}
    assert s['modelled_cameras'] == 10
    assert s['stop_reason'] == 'stopped after c1 failed to model'
    # 5,000 of 5,030 cameras unbuilt must not read as a near-complete run.
    assert 100.0 * s['modelled_cameras'] / s['candidate_cameras'] < 1.0


def test_totals_reconcile_against_the_candidate_list():
    """Every candidate camera lands in exactly one bucket."""
    finals = [_final(f'c{i}', (i + 1) * 100) for i in range(5)]
    models = [_model('c0', 100, success=True),
              _model('c1', 200, success=True),
              _model('c2', 300, skipped='scale_gate'),
              _model('c3', 400, success=False, errors='boom'),
              _model('c4', 500, skipped='not_reached')]
    s = summarise_models(models, finals)
    counted = (s['modelled_cameras'] + s['failed_cameras']
               + sum(v['cameras'] for v in s['skipped'].values()))
    assert counted == s['candidate_cameras'] == 1500


def test_already_modelled_is_not_double_counted():
    """Carried-forward successes stay successes and must not ALSO appear as a
    skip - that would make the component count exceed the candidate count."""
    finals = [_final('c0', 100), _final('c1', 200)]
    models = [_model('c0', 100, success=True),     # carried from a prior run
              _model('c1', 200, success=True)]
    s = summarise_models(models, finals)
    assert s['modelled'] == 2
    assert sum(v['components'] for v in s['skipped'].values()) == 0
    assert s['modelled'] + s['failed'] <= s['candidates']


# ------------------------------------------------------------------ rendering

def test_the_log_names_the_scale_refusal_and_its_cost():
    finals = [_final('c0', 100), _final('c1', 900)]
    models = [_model('c0', 100, success=True),
              _model('c1', 900, skipped='scale_gate')]
    text = '\n'.join(summary_lines(summarise_models(models, finals)))
    assert 'MODELLED' in text and '10.0%' in text
    assert 'scale_gate' in text
    assert 'NO deliverable' in text
    # and it must steer AWAY from --force, which changes nothing metric
    assert '--force' in text and 'does not correct the scale' in text


def test_error_level_lines_are_marked():
    finals = [_final('c0', 100)]
    models = [_model('c0', 100, success=False, errors='boom')]
    lines = summary_lines(summarise_models(models, finals, stop_reason='disk floor'))
    assert any(l.startswith('!') for l in lines), lines
    assert any('stopped early' in l for l in lines)


def test_a_zero_candidate_summary_does_not_divide_by_zero():
    s = summarise_models([], [])
    assert s['candidate_cameras'] == 0
    summary_lines(s)      # must not raise
