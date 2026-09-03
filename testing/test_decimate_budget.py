"""
Decimation to a triangle budget, and the 4K output cap.

Three things are pinned here.

1. THE PASS COUNT IS DERIVED, NOT FIXED. `GenerateModel.bat` ends every
   component with four relative-80% passes. 0.8^4 = 41%, a fixed RATIO, so the
   result is only as small as the input: H2060's twenty "Simplified" models
   landed between 2.8 M and 42.4 M triangles. Reaching a budget needs
   ceil(log(budget/N0)/log(0.8)) passes computed per component.

2. NEVER A DESTRUCTIVE OPERATION AFTER AN UNVERIFIED SELECT. `-selectModel` on
   a name that does not exist is a SILENT NO-OP - the previous selection stays
   active and lastError stays 0 (proven 2026-09-03). So `-selectModel X` +
   `-deleteSelectedModel` deletes whatever was selected before when X is
   absent. That destroyed c15's `_HighPoly_Raw` mid-run. `select()` must prove
   the selection by reading the model name back, and `delete()` must refuse to
   act when it cannot.

3. THE 4K CAP. Owner, 2026-09-03: "we should never be exporting 16k files."
   The new adaptive presets must stay at or under 4096.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from run_decimate import PASS_RATIO, passes_for

META = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    'modules', 'realityscan_interface', 'RS_CLI', 'Metadata')

ADAPTIVE = ('Texturing_AdaptiveTexel_4k.xml', 'Unwrapping_AdaptiveTexel_4k.xml')


def _entries(name):
    import re
    with open(os.path.join(META, name), encoding='utf-8') as fh:
        return dict(re.findall(r'key="([^"]+)"\s+value="([^"]*)"', fh.read()))


# ----------------------------------------------------------------- pass count
def test_already_inside_budget_needs_no_passes():
    assert passes_for(400_000, 500_000) == 0
    assert passes_for(500_000, 500_000) == 0


def test_pass_count_actually_reaches_the_budget():
    # The whole point: however big the input, the computed count must land it.
    for start in (2_770_844, 6_785_576, 10_695_953, 42_414_945, 103_548_208):
        n = passes_for(start, 500_000)
        assert start * PASS_RATIO ** n <= 500_000, (start, n)
        # ...and must not overshoot by a whole extra pass, which throws away
        # detail for nothing.
        assert start * PASS_RATIO ** (n - 1) > 500_000, (start, n)


def test_h2060_measured_components_need_9_to_20_passes():
    # Real measurements from the master project, smallest and largest.
    assert passes_for(2_770_844, 500_000) == 8
    assert passes_for(42_414_945, 500_000) == 20


def test_four_fixed_passes_is_only_41_percent():
    # Why the old flow could not hit a budget, stated as a number.
    assert round(PASS_RATIO ** 4, 4) == 0.4096
    assert 42_414_945 * PASS_RATIO ** 4 > 17_000_000


def test_none_is_treated_as_nothing_to_do():
    assert passes_for(None, 500_000) == 0


# ------------------------------------------------------- verified select/delete
class FakeRs:
    """Mimics the instance: selecting a missing model is a silent no-op."""

    def __init__(self, models, selected):
        self.models = dict(models)
        self.selected = selected
        self.deleted = []

    def cmd(self, *args, **kw):
        if args[0] == '-selectModel':
            if args[1] in self.models:          # silent no-op when absent
                self.selected = args[1]
        elif args[0] == '-deleteSelectedModel':
            self.deleted.append(self.selected)
            self.models.pop(self.selected, None)
        elif args[0] == '-renameSelectedModel':
            self.models[args[1]] = self.models.pop(self.selected)
            self.selected = args[1]

    def report(self):
        return self.selected, self.models.get(self.selected)


def _bind(fake):
    from run_decimate import Rs
    fake.select = lambda m: Rs.select(fake, m)
    fake.delete = lambda m: Rs.delete(fake, m)
    fake.rename = lambda m: Rs.rename(fake, m)
    fake.measure = lambda m: Rs.measure(fake, m)
    return fake


def test_select_returns_false_for_a_missing_model():
    rs = _bind(FakeRs({'keep': 10}, 'keep'))
    assert rs.select('keep') is True
    assert rs.select('ghost') is False


def test_delete_of_a_missing_model_deletes_NOTHING():
    # The regression that destroyed c15's high-poly source.
    rs = _bind(FakeRs({'working': 10}, 'working'))
    assert rs.delete('ghost') is False
    assert rs.deleted == []
    assert 'working' in rs.models


def test_delete_of_a_present_model_removes_that_model():
    rs = _bind(FakeRs({'working': 10, 'scrap': 5}, 'working'))
    assert rs.delete('scrap') is True
    assert rs.deleted == ['scrap']
    assert 'working' in rs.models


def test_measure_of_a_missing_model_is_None_not_the_wrong_count():
    # Without the name check this returns the PREVIOUS model's triangle count,
    # which would silently compute a pass count for the wrong mesh.
    rs = _bind(FakeRs({'big': 42_414_945}, 'big'))
    assert rs.measure('big') == 42_414_945
    assert rs.measure('ghost') is None


# ------------------------------------------------------------------- 4K cap
@pytest.mark.parametrize('name', ADAPTIVE)
def test_adaptive_presets_use_the_adaptive_style(name):
    # Not MaxTexturesCount - that is a different style the repo used to call
    # "the adaptive mode".
    assert _entries(name)['unwrapStyle'] == 'AdaptiveTexelSize'


@pytest.mark.parametrize('name', ADAPTIVE)
def test_adaptive_presets_declare_the_texel_clamp(name):
    e = _entries(name)
    assert e['unwrapMinTexelSize'] == '0'      # optimal
    assert e['unwrapMaxTexelSize'] == '4'      # 100x optimal
    assert 'unwrapMaximalTexCount' not in e    # belongs to MaxTexturesCount


@pytest.mark.parametrize('name', ADAPTIVE)
def test_adaptive_presets_never_exceed_4096(name):
    assert int(_entries(name)['unwrapMaxTexResolution']) <= 4096


def test_the_obj_export_writes_jpg_textures():
    e = _entries('ModelExportParamsObj.xml')
    assert e['MvsMeshExportTexImgFormat_Color8_0'] == 'jpg'


def test_no_16k_hides_in_the_new_presets():
    for name in ADAPTIVE:
        with open(os.path.join(META, name), encoding='utf-8') as fh:
            assert '16384' not in fh.read(), name


# --------------------------------------------------- component scoping
def test_measure_selects_the_component_first_when_asked():
    # `-selectModel` resolves only within the ACTIVE component. The resume
    # check measures `<comp>_Dec500k` for a component that is not active, so it
    # MUST select the component first - without this every finished component
    # measures as absent and gets re-textured from scratch.
    calls = []

    class Spy(FakeRs):
        def cmd(self, *args, **kw):
            calls.append(args[0])
            super().cmd(*args, **kw)

    rs = _bind(Spy({'m': 7}, 'm'))
    from run_decimate import Rs
    rs.measure = lambda model, component=None: Rs.measure(rs, model, component)
    rs.measure('m', component='comp0')
    assert calls[0] == '-selectComponent'
    calls.clear()
    rs.measure('m')
    assert '-selectComponent' not in calls
