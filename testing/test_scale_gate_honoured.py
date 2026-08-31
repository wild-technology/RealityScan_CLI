"""
Workspace modelling must honour the merge report's recorded --scale_gate
answer.

merge_zones writes {"scale_gate": {"enabled": bool, "min": .., "max": ..}}.
run_models' modelling loop gated unconditionally and never read it, so a
workspace deliberately assembled with --scale_gate false still had its
out-of-band components REFUSED with "SCALE GATE: <name> not modelled".

Observed on NA165/H2060 (2026-08-31): the owner asked for every component to
be modelled and exported regardless of scale; the assembly recorded
enabled=false; run_models skipped zone_all_c18 and zone_all_c16 anyway.

Disabling the gate stops it REFUSING, not MEASURING - the measured scale is
still written into the model entry either way.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run_models import scale_gate_enabled


def test_enabled_false_disables_the_gate():
    assert scale_gate_enabled({'scale_gate': {'enabled': False,
                                              'min': 0.9, 'max': 1.1}}) is False


def test_enabled_true_keeps_the_gate():
    assert scale_gate_enabled({'scale_gate': {'enabled': True,
                                              'min': 0.9, 'max': 1.1}}) is True


def test_absent_field_keeps_gating():
    # An older report predating the field must keep gating: silently MODELLING
    # what a previous run refused is worse than redundantly refusing.
    assert scale_gate_enabled({}) is True
    assert scale_gate_enabled({'scale_gate': None}) is True


def test_malformed_field_keeps_gating():
    assert scale_gate_enabled({'scale_gate': 'false'}) is True
    assert scale_gate_enabled({'scale_gate': {'enabled': 'no'}}) is True
    assert scale_gate_enabled({'scale_gate': {}}) is True


def test_real_report_shape_from_the_run(tmp_path):
    # The exact shape merge_zones wrote for the NA165 master assembly.
    import json
    report = json.loads('{"schema":1,"scale_gate":{"enabled":false,'
                        '"min":0.9,"max":1.1},"clusters":[]}')
    assert scale_gate_enabled(report) is False
