"""Per-feature merge planning: 3D extents, box assignment, ceiling-aware
staged plans (PRODUCT_READINESS must-fix 1 groundwork)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.feature_merge import (
    FeatureBox, assign_components, component_extent, load_feature_boxes,
    load_nav_positions, plan_feature_merge)

NAV = {
    "L_a.jpg": (0.0, 0.0, -5.0), "R_a.jpg": (0.17, 0.0, -5.0),
    "L_m.jpg": (10.0, 2.0, 12.0), "R_m.jpg": (10.17, 2.0, 12.0),
}


def _c(key, cams, members):
    return {"key": key, "rsalign": key + ".rsalign",
            "camera_count": cams, "members": members}


def test_component_extent_carries_z_and_refuses_to_invent():
    ext = component_extent(["L_a.jpg", "R_a.jpg", "missing.jpg"], NAV)
    assert ext["bbox"][2] == -5.0 and ext["bbox"][5] == -5.0
    assert ext["with_nav"] == 2 and ext["members"] == 3
    assert component_extent(["nope.jpg"], NAV) is None


def test_assignment_specific_box_wins_and_unlocatable_is_flagged():
    boxes = [FeatureBox("mast_a", zmin=5.0),          # anything high
             FeatureBox("hull")]                       # catch-all
    comps = [_c("hullish", 100, ["L_a.jpg", "R_a.jpg"]),
             _c("masty", 40, ["L_m.jpg", "R_m.jpg"]),
             _c("ghost", 10, ["unknown.jpg"])]
    out = assign_components(comps, NAV, boxes, default_feature="hull")
    assert [c["key"] for c in out["mast_a"]] == ["masty"]
    assert [c["key"] for c in out["hull"]] == ["hullish"]
    assert [c["key"] for c in out["_unassigned"]] == ["ghost"]


def test_plan_single_stage_when_it_fits():
    comps = [_c("z1", 3000, []), _c("z2", 2000, [])]
    plan = plan_feature_merge(comps, ceiling=34000)
    assert len(plan) == 1
    assert plan[0].est_scene_cameras == 5000


def test_plan_accepts_the_measured_on2026_fusion_shape():
    # the ACCEPTED attempt-1 fusion: 10 components, 34,105 cams, fit in
    # 262 GB - a ceiling of 34,200 admits it in one stage
    sizes = [4442, 4119, 3734, 3592, 3363, 3288, 3134, 2846, 2650, 2937]
    plan = plan_feature_merge([_c(f"z{i}", s, []) for i, s in enumerate(sizes)],
                              ceiling=34200)
    assert len(plan) == 1 and plan[0].est_scene_cameras == sum(sizes)


def test_plan_refuses_over_ceiling_totals_because_counts_are_additive():
    # staged fold-into-core cannot escape the ceiling: the final scene
    # holds ~the total. The planner must refuse, naming operator options.
    sizes = [4442, 4119, 3734, 3592, 3363, 3288, 3134, 2846, 2650, 2614, 2262]
    with pytest.raises(ValueError) as exc:
        plan_feature_merge([_c(f"z{i}", s, []) for i, s in enumerate(sizes)],
                           ceiling=34000)
    assert "additive" in str(exc.value)
    assert "redraw" in str(exc.value)


def test_plan_empty_feature_is_empty_plan():
    assert plan_feature_merge([], ceiling=34000) == []


def test_load_nav_positions_and_boxes(tmp_path):
    log = tmp_path / "flight_log_run2.txt"
    log.write_text(
        "filename;x;y;alt;acc\nL_a.jpg;1;2;3;0.02\nbad;row\n",
        encoding="utf-8")
    nav = load_nav_positions(str(log))
    assert nav == {"L_a.jpg": (1.0, 2.0, 3.0)}

    fj = tmp_path / "features.json"
    fj.write_text(
        '{"confirmed": false, "default_feature": "hull", "features": ['
        '{"name": "mast_a", "xmin": 8, "xmax": 12, "zmin": 4},'
        '{"name": "hull"}]}', encoding="utf-8")
    boxes, default, confirmed = load_feature_boxes(str(fj))
    assert [b.name for b in boxes] == ["mast_a", "hull"]
    assert default == "hull" and confirmed is False
    assert boxes[0].contains((10, 0, 6)) and not boxes[0].contains((10, 0, 0))
