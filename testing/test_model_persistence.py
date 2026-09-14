#!/usr/bin/env python3
"""A model that was not saved must never be recorded as a success (2026-09-14).

WHY THIS EXISTS. NA165/H2060, twice, identically:

    2026-09-13 01:12  === model zone_2_c0 (1831 cams, scale 0.995) ===
    2026-09-13 03:30  model zone_2_c0: success=True in 137.8 min
    2026-09-13 03:30  ... disk floor: under 50 GB free (0.0 GB free now)

The volume was at ZERO bytes free when a 138-minute model tried to save.
Nothing was written, GenerateModel.bat still returned 0, and `success=True`
went into models_report.json for a model that does not exist.

That record is the damaging part, not the lost model. The resume logic keys on
it, so the next run logged "SKIP zone_2_c0: already modelled in an earlier run;
its success record carries forward" and moved on. The absence only surfaced
three days later, when ExportDeliverables failed on it with a bare E_FAIL in 0
seconds and killed the remaining exports with it - a fault reported at the far
end of the pipeline from where it happened.

Re-modelling it on 2026-09-14 reproduced the failure exactly (164.9 min,
success=True, 0.0 GB free, project mtime still predating the run), which is
what moved this from "an odd one-off" to a defect with a test.

The rule: an exit code says the workflow RAN; only the artefact says it
SURVIVED. Where the two can disagree, trust the artefact.

Run:  python -m pytest testing/test_model_persistence.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run_models import model_persisted  # noqa: E402


def _project(tmp_path, *model_names):
    """A stand-in .rsproj carrying the model names a real one would.

    -renameSelectedModel writes the name into the project file, which is
    exactly why its presence is usable as evidence; the surrounding XML is
    irrelevant to the check, so the fixture does not fake it.
    """
    p = tmp_path / 'Assembly.rsproj'
    body = '<project>' + ''.join(
        '<model name="%s"/>' % n for n in model_names) + '</project>'
    p.write_bytes(body.encode('utf-8'))
    return p


def test_present_model_is_persisted(tmp_path):
    proj = _project(tmp_path, 'zone_1_c0_Simplified_Textured')
    assert model_persisted(proj, 'zone_1_c0')


def test_the_incident_absent_model_is_not_persisted(tmp_path):
    """The real shape: 38 components saved, the 39th silently did not."""
    names = ['zone_1_c%d_Simplified_Textured' % i for i in range(38)]
    proj = _project(tmp_path, *names)
    assert model_persisted(proj, 'zone_1_c0')
    assert not model_persisted(proj, 'zone_2_c0')


def test_an_intermediate_model_does_not_count_as_the_deliverable(tmp_path):
    """GenerateModel renames through a dozen intermediates on its way to
    _Simplified_Textured (_HighPoly_Raw, _Cleanup1.., _Manifold, _Simplified).
    A project holding only intermediates is a model that did not FINISH, and
    ExportDeliverables asks for _Simplified_Textured by name - so a check that
    matched the bare component name would pass on a project the export cannot
    use."""
    proj = _project(tmp_path,
                    'zone_2_c0_HighPoly_Raw',
                    'zone_2_c0_HighPoly_Textured',
                    'zone_2_c0_Simplified')
    assert not model_persisted(proj, 'zone_2_c0')


def test_a_missing_project_is_not_evidence_of_success(tmp_path):
    """Fail safe. A false negative costs a re-model; a false positive is the
    incident this file documents."""
    assert not model_persisted(tmp_path / 'does_not_exist.rsproj', 'zone_2_c0')


def test_an_unreadable_project_is_not_evidence_of_success(tmp_path):
    """A directory where a project should be: read_bytes raises OSError, and
    silence must not be read as a pass."""
    d = tmp_path / 'Assembly.rsproj'
    d.mkdir()
    assert not model_persisted(d, 'zone_2_c0')


def test_empty_project_is_not_evidence_of_success(tmp_path):
    """What a save onto a full disk can actually leave behind."""
    p = tmp_path / 'Assembly.rsproj'
    p.write_bytes(b'')
    assert not model_persisted(p, 'zone_2_c0')


def test_component_names_do_not_prefix_match_each_other(tmp_path):
    """zone_2_c1 must not be satisfied by zone_2_c11's model. The names in
    this dive really do collide that way - c1/c11/c18, c0/c0x - so a
    substring check on the component name alone would report a component as
    persisted because a DIFFERENT one was."""
    proj = _project(tmp_path, 'zone_2_c11_Simplified_Textured')
    assert model_persisted(proj, 'zone_2_c11')
    assert not model_persisted(proj, 'zone_2_c1')


if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main([__file__, '-v']))
