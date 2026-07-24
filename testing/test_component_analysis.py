#!/usr/bin/env python3
"""Unit tests for modules/component_analysis.py (pure functions only).

Synthetic schema-v1 manifests; no RealityScan, no filesystem beyond the
load_manifests round-trip test.

Run:  py -3.13 -m pytest testing/test_component_analysis.py
"""

from __future__ import annotations

import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO_ROOT)

from modules.component_analysis import (  # noqa: E402
    choose_keeper,
    component_key,
    containment,
    find_borders,
    find_twins,
    load_manifests,
    merge_plan,
    orphan_images,
)


def make_manifest(zone, component, images, camera_count=None, bbox=None,
                  mean_reproj=None):
    return {
        "schema": 1,
        "zone": zone,
        "component": component,
        "rsalign": "D:/fake/{0}/{1}.rsalign".format(zone, component),
        "images": list(images),
        "camera_count": len(images) if camera_count is None else camera_count,
        "bbox_utm": bbox,
        "quality": {"mean_reproj_px": mean_reproj},
        "created": "2026-07-23T00:00:00+00:00",
        "history": [{"event": "aligned", "at": "2026-07-23T00:00:00+00:00"}],
    }


def imgs(prefix, n, start=0):
    return ["{0}_{1:05d}.jpg".format(prefix, i) for i in range(start, start + n)]


# ---------------------------------------------------------------------------
# find_twins
# ---------------------------------------------------------------------------

class TestFindTwins:
    def test_exact_twin_cross_zone(self):
        shared = imgs("band", 40)
        big = make_manifest("zone_1", "c0", imgs("z1", 200) + shared)
        weak = make_manifest("zone_2", "c1", shared)
        result = find_twins([big, weak])

        full = [p for p in result["pairs"] if p["classification"] == "full"]
        assert len(full) == 1
        assert full[0]["contained"] == "zone_2/c1"
        assert full[0]["container"] == "zone_1/c0"
        assert full[0]["containment"] == 1.0
        assert full[0]["unique_images_in_contained"] == 0
        assert full[0]["cross_zone"] is True

        assert len(result["groups"]) == 1
        assert result["groups"][0]["members"] == ["zone_1/c0", "zone_2/c1"]
        assert result["groups"][0]["cross_zone"] is True

    def test_partial_twin_with_unique_images(self):
        # 19 of 20 images shared -> containment 0.95 but one unique image.
        shared = imgs("band", 19)
        big = make_manifest("zone_1", "c0", imgs("z1", 100) + shared)
        partial = make_manifest("zone_2", "c1", shared + ["unique_only.jpg"])
        result = find_twins([big, partial])

        pairs = result["pairs"]
        assert len(pairs) == 1
        assert pairs[0]["classification"] == "partial"
        assert pairs[0]["contained"] == "zone_2/c1"
        assert pairs[0]["unique_images_in_contained"] == 1

    def test_containment_threshold_edges(self):
        big = make_manifest("zone_1", "c0", imgs("band", 100) + imgs("z1", 50))
        # Exactly at threshold: 19/20 = 0.95 -> detected.
        at_edge = make_manifest("zone_2", "at", imgs("band", 19) + ["x.jpg"])
        # Just below: 18/20 = 0.90 -> not detected.
        below = make_manifest("zone_3", "below", imgs("band", 18) + imgs("q", 2))

        result = find_twins([big, at_edge], containment_threshold=0.95)
        assert len(result["pairs"]) == 1

        result = find_twins([big, below], containment_threshold=0.95)
        assert result["pairs"] == []
        assert result["groups"] == []

    def test_within_zone_twin_detected(self):
        a = make_manifest("zone_1", "c0", imgs("s", 30))
        b = make_manifest("zone_1", "c1", imgs("s", 30))
        result = find_twins([a, b])
        assert len(result["pairs"]) == 2  # mutual full containment
        assert all(p["cross_zone"] is False for p in result["pairs"])
        assert result["groups"][0]["cross_zone"] is False

    def test_disjoint_components_no_twins(self):
        a = make_manifest("zone_1", "c0", imgs("a", 30))
        b = make_manifest("zone_2", "c0", imgs("b", 30))
        result = find_twins([a, b])
        assert result["pairs"] == []
        assert result["groups"] == []

    def test_containment_helper(self):
        a = make_manifest("z", "a", imgs("s", 10))
        b = make_manifest("z2", "b", imgs("s", 5))
        assert containment(b, a) == 1.0
        assert containment(a, b) == 0.5
        empty = make_manifest("z3", "e", [])
        assert containment(empty, a) == 1.0  # no images -> nothing unique


# ---------------------------------------------------------------------------
# choose_keeper
# ---------------------------------------------------------------------------

class TestChooseKeeper:
    def test_prefers_higher_camera_count(self):
        shared = imgs("band", 40)
        big = make_manifest("zone_1", "c0", imgs("z1", 200) + shared,
                            mean_reproj=1.5)
        weak = make_manifest("zone_2", "c1", shared, mean_reproj=0.4)
        decision = choose_keeper([big, weak])
        assert decision["keeper"] == "zone_1/c0"
        assert [d["component"] for d in decision["discards"]] == ["zone_2/c1"]
        assert decision["retained"] == []
        assert "no unique images" in decision["discards"][0]["reason"]

    def test_tiebreak_by_quality(self):
        shared = imgs("band", 30)
        crisp = make_manifest("zone_1", "c0", shared, mean_reproj=0.5)
        blurry = make_manifest("zone_2", "c0", shared, mean_reproj=2.0)
        decision = choose_keeper([crisp, blurry])
        assert decision["keeper"] == "zone_1/c0"
        assert [d["component"] for d in decision["discards"]] == ["zone_2/c0"]

    def test_missing_quality_loses_tiebreak(self):
        shared = imgs("band", 30)
        known = make_manifest("zone_1", "c0", shared, mean_reproj=3.0)
        unknown = make_manifest("zone_2", "c0", shared, mean_reproj=None)
        decision = choose_keeper([known, unknown])
        assert decision["keeper"] == "zone_1/c0"

    def test_tiebreak_by_zone_network_size(self):
        shared = imgs("band", 30)
        a = make_manifest("zone_1", "c0", shared)
        b = make_manifest("zone_2", "c0", shared)
        decision = choose_keeper(
            [a, b], zone_network_sizes={"zone_1": 100, "zone_2": 4000})
        assert decision["keeper"] == "zone_2/c0"
        decision = choose_keeper(
            [a, b], zone_network_sizes={"zone_1": 4000, "zone_2": 100})
        assert decision["keeper"] == "zone_1/c0"

    def test_never_discards_unique_images(self):
        # Partial twin: worst quality, smallest network, but one unique
        # image -> must be retained, never discarded.
        shared = imgs("band", 19)
        big = make_manifest("zone_1", "c0", imgs("z1", 100) + shared,
                            mean_reproj=0.5)
        partial = make_manifest("zone_2", "c1", shared + ["unique_only.jpg"],
                                mean_reproj=9.9)
        decision = choose_keeper([big, partial])
        assert decision["keeper"] == "zone_1/c0"
        assert decision["discards"] == []
        assert [r["component"] for r in decision["retained"]] == ["zone_2/c1"]
        assert "never discardable" in decision["retained"][0]["reason"]

    def test_union_coverage_three_way(self):
        # c2's images are covered only by the UNION of c0 and c1; both
        # are kept, so c2 is discardable. c0 and c1 each hold uniques.
        left, right = imgs("left", 20), imgs("right", 20)
        c0 = make_manifest("zone_1", "c0", left + imgs("l_extra", 5))
        c1 = make_manifest("zone_1", "c1", right + imgs("r_extra", 5))
        c2 = make_manifest("zone_2", "c2", left + right)
        decision = choose_keeper([c0, c1, c2])
        # c2 has the highest camera_count (40) so it is the keeper; the
        # others hold unique images and are retained -- nothing discards.
        assert decision["keeper"] == "zone_2/c2"
        assert decision["discards"] == []
        assert len(decision["retained"]) == 2

    def test_identical_triplet_keeps_exactly_one(self):
        shared = imgs("band", 25)
        trip = [make_manifest("zone_{0}".format(i), "c0", shared,
                              mean_reproj=float(i)) for i in (1, 2, 3)]
        decision = choose_keeper(trip)
        assert decision["keeper"] == "zone_1/c0"  # lowest reproj
        assert sorted(d["component"] for d in decision["discards"]) == \
            ["zone_2/c0", "zone_3/c0"]
        assert decision["retained"] == []

    def test_empty_group_raises(self):
        with pytest.raises(ValueError):
            choose_keeper([])


# ---------------------------------------------------------------------------
# find_borders
# ---------------------------------------------------------------------------

class TestFindBorders:
    def test_adjacent_within_margin(self):
        a = make_manifest("zone_1", "c0", imgs("a", 5),
                          bbox=[0.0, 0.0, 100.0, 100.0])
        # 15 m gap; margin 10 on each side -> expanded boxes touch.
        b = make_manifest("zone_2", "c0", imgs("b", 5),
                          bbox=[115.0, 0.0, 200.0, 100.0])
        result = find_borders([a, b], margin_m=10.0)
        assert len(result) == 1
        assert result[0]["pair"] == ["zone_1/c0", "zone_2/c0"]
        assert result[0]["reason"] == "bbox_overlap_within_margin"
        assert result[0]["cross_zone"] is True

    def test_distant_not_candidates(self):
        a = make_manifest("zone_1", "c0", imgs("a", 5),
                          bbox=[0.0, 0.0, 100.0, 100.0])
        # 21 m gap > 2 * 10 m margin -> no border.
        b = make_manifest("zone_2", "c0", imgs("b", 5),
                          bbox=[121.0, 0.0, 200.0, 100.0])
        assert find_borders([a, b], margin_m=10.0) == []

    def test_gap_exactly_double_margin_borders(self):
        a = make_manifest("zone_1", "c0", imgs("a", 5),
                          bbox=[0.0, 0.0, 100.0, 100.0])
        b = make_manifest("zone_2", "c0", imgs("b", 5),
                          bbox=[120.0, 0.0, 200.0, 100.0])
        assert len(find_borders([a, b], margin_m=10.0)) == 1

    def test_diagonal_offset_not_candidate(self):
        a = make_manifest("zone_1", "c0", imgs("a", 5),
                          bbox=[0.0, 0.0, 100.0, 100.0])
        b = make_manifest("zone_2", "c0", imgs("b", 5),
                          bbox=[105.0, 130.0, 200.0, 220.0])  # y-gap 30 m
        assert find_borders([a, b], margin_m=10.0) == []

    def test_null_bbox_pairs_with_everything(self):
        a = make_manifest("zone_1", "c0", imgs("a", 5),
                          bbox=[0.0, 0.0, 100.0, 100.0])
        far = make_manifest("zone_2", "c0", imgs("b", 5),
                            bbox=[5000.0, 5000.0, 5100.0, 5100.0])
        unknown = make_manifest("zone_3", "c0", imgs("c", 5), bbox=None)
        result = find_borders([a, far, unknown], margin_m=10.0)
        reasons = {tuple(r["pair"]): r["reason"] for r in result}
        assert ("zone_1/c0", "zone_3/c0") in reasons
        assert ("zone_2/c0", "zone_3/c0") in reasons
        assert all(v == "unknown_bbox" for v in reasons.values())
        assert ("zone_1/c0", "zone_2/c0") not in reasons  # far apart


# ---------------------------------------------------------------------------
# orphan_images
# ---------------------------------------------------------------------------

class TestOrphanImages:
    def test_orphans_computed(self):
        a = make_manifest("zone_1", "c0", imgs("a", 3))
        b = make_manifest("zone_2", "c0", imgs("b", 3))
        everything = imgs("a", 3) + imgs("b", 3) + ["lost_1.jpg", "lost_2.jpg"]
        assert orphan_images([a, b], everything) == ["lost_1.jpg", "lost_2.jpg"]

    def test_no_orphans(self):
        a = make_manifest("zone_1", "c0", imgs("a", 3))
        assert orphan_images([a], imgs("a", 3)) == []

    def test_no_manifests_all_orphans(self):
        assert orphan_images([], ["x.jpg"]) == ["x.jpg"]


# ---------------------------------------------------------------------------
# merge_plan
# ---------------------------------------------------------------------------

class TestMergePlan:
    def build_scenario(self):
        band12 = imgs("band12", 40)
        z1 = make_manifest("zone_1", "c0", imgs("z1", 300) + band12,
                           bbox=[0.0, 0.0, 100.0, 100.0], mean_reproj=0.8)
        # Weak twin of the band inside zone_2 -- fully contained in z1.
        twin = make_manifest("zone_2", "c1", band12,
                             bbox=[95.0, 0.0, 130.0, 100.0], mean_reproj=2.5)
        z2 = make_manifest("zone_2", "c0", imgs("z2", 200),
                           bbox=[100.0, 0.0, 200.0, 100.0], mean_reproj=1.0)
        z3 = make_manifest("zone_3", "c0", imgs("z3", 150),
                           bbox=[200.0, 0.0, 300.0, 100.0], mean_reproj=1.1)
        far = make_manifest("zone_9", "c0", imgs("z9", 50),
                            bbox=[9000.0, 9000.0, 9100.0, 9100.0])
        return z1, twin, z2, z3, far

    def test_twins_resolved_and_discard_excluded(self):
        z1, twin, z2, z3, far = self.build_scenario()
        plan = merge_plan([z1, twin, z2, z3, far])
        assert plan["discards"] == ["zone_2/c1"]
        assert plan["twin_resolutions"][0]["keeper"] == "zone_1/c0"
        for cand in plan["merge_candidates"]:
            assert "zone_2/c1" not in cand["pair"]

    def test_candidates_border_gated_and_cross_zone(self):
        z1, twin, z2, z3, far = self.build_scenario()
        plan = merge_plan([z1, twin, z2, z3, far])
        pairs = [tuple(c["pair"]) for c in plan["merge_candidates"]]
        assert ("zone_1/c0", "zone_2/c0") in pairs
        assert ("zone_2/c0", "zone_3/c0") in pairs
        # zone_9 is distant with a known bbox -> gated out entirely.
        assert not any("zone_9/c0" in p for p in pairs)
        # zone_1 and zone_3 are 100 m apart -> not bordering.
        assert ("zone_1/c0", "zone_3/c0") not in pairs

    def test_ordering_largest_first(self):
        z1, twin, z2, z3, far = self.build_scenario()
        plan = merge_plan([z1, twin, z2, z3, far])
        sizes = [c["combined_camera_count"] for c in plan["merge_candidates"]]
        assert sizes == sorted(sizes, reverse=True)
        assert plan["merge_candidates"][0]["pair"] == ["zone_1/c0", "zone_2/c0"]
        priorities = [c["priority"] for c in plan["merge_candidates"]]
        assert priorities == list(range(1, len(priorities) + 1))

    def test_plan_serializable_with_orphans(self):
        z1, twin, z2, z3, far = self.build_scenario()
        all_images = (z1["images"] + z2["images"] + z3["images"] +
                      far["images"] + ["orphan.jpg"])
        plan = merge_plan([z1, twin, z2, z3, far], all_images=all_images)
        assert plan["orphan_images"] == ["orphan.jpg"]
        round_trip = json.loads(json.dumps(plan))
        assert round_trip["discards"] == ["zone_2/c1"]

    def test_within_zone_pairs_reported_separately(self):
        a = make_manifest("zone_1", "c0", imgs("a", 30),
                          bbox=[0.0, 0.0, 50.0, 50.0])
        b = make_manifest("zone_1", "c1", imgs("b", 30),
                          bbox=[55.0, 0.0, 100.0, 50.0])
        plan = merge_plan([a, b])
        assert plan["merge_candidates"] == []
        assert len(plan["within_zone_border_pairs"]) == 1

    def test_partial_twin_survives_into_candidates(self):
        shared = imgs("band", 19)
        big = make_manifest("zone_1", "c0", imgs("z1", 100) + shared,
                            bbox=[0.0, 0.0, 100.0, 100.0], mean_reproj=0.5)
        partial = make_manifest("zone_2", "c1", shared + ["unique_only.jpg"],
                                bbox=[95.0, 0.0, 150.0, 100.0], mean_reproj=9.9)
        plan = merge_plan([big, partial])
        assert plan["discards"] == []
        pairs = [tuple(c["pair"]) for c in plan["merge_candidates"]]
        assert ("zone_1/c0", "zone_2/c1") in pairs


# ---------------------------------------------------------------------------
# Validation + loader
# ---------------------------------------------------------------------------

class TestValidationAndLoader:
    def test_bad_schema_rejected(self):
        bad = make_manifest("zone_1", "c0", imgs("a", 3))
        bad["schema"] = 2
        with pytest.raises(ValueError):
            find_twins([bad])

    def test_duplicate_identity_rejected(self):
        a = make_manifest("zone_1", "c0", imgs("a", 3))
        b = make_manifest("zone_1", "c0", imgs("b", 3))
        with pytest.raises(ValueError):
            find_twins([a, b])

    def test_load_manifests_round_trip(self, tmp_path):
        m = make_manifest("zone_1", "c0", imgs("a", 3))
        sub = tmp_path / "zone_1"
        sub.mkdir()
        path = sub / "zone_1_c0.rsalign.manifest.json"
        path.write_text(json.dumps(m), encoding="utf-8")
        (sub / "not_a_manifest.json").write_text("{}", encoding="utf-8")
        loaded = load_manifests(str(tmp_path))
        assert len(loaded) == 1
        assert component_key(loaded[0]) == "zone_1/c0"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
