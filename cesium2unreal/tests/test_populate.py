"""Dry-run cesium2unreal.populate against a fake editor. No Unreal required.

What this actually proves: that the height correction lands along the local
vertical (not the origin's +Z), that re-running does not duplicate actors, that
the terrain tileset is not treated as a model, that an unsampled site is left
where ion put it, and that the reported deltas are the ones applied.
"""

import json
import math
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

import fake_unreal                                    # noqa: E402

# populate.py imports `unreal` at module scope, so the stand-in has to be
# installed before the package is touched.
sys.modules["unreal"] = fake_unreal

from cesium2unreal import populate as cesium_populate  # noqa: E402

ORIGIN = (-64.7500, 32.3000, 0.0)                     # lon, lat, height
TERRAIN_ID = 9000


def _write(obj):
    fh = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(obj, fh)
    fh.close()
    return fh.name


class _LevelFixture(unittest.TestCase):
    """A level with a georeference, a terrain tileset and a manifest."""

    def setUp(self):
        fake_unreal.reset()
        self.georef = fake_unreal.CesiumGeoreference(*ORIGIN)
        self.georef.set_actor_label("CesiumGeoreference")
        self.terrain = fake_unreal.Cesium3DTileset()
        self.terrain.set_actor_label("Bathymetry")
        self.terrain.set_editor_property("ion_asset_id", TERRAIN_ID)
        self.terrain.set_editor_property("create_physics_meshes", True)
        fake_unreal._Level.actors = [self.georef, self.terrain]

        # Seafloor at a constant -1200 m, except one hole with no coverage.
        fake_unreal.TERRAIN_FN = lambda lon, lat: None if lat > 33.0 else -1200.0

        self.manifest = [
            # at the origin, so the offset must be purely +Z
            {"id": 101, "name": "Transect_01", "lon": ORIGIN[0], "lat": ORIGIN[1],
             "height": -1150.0},
            # ~50 km east, where local up has diverged from the origin's +Z
            {"id": 102, "name": "Transect_02", "lon": ORIGIN[0] + 0.53, "lat": ORIGIN[1],
             "height": -1180.0},
            # north of the terrain coverage: sampling fails here
            {"id": 103, "name": "Transect_03", "lon": ORIGIN[0], "lat": 33.5,
             "height": -900.0},
            # the terrain itself, which must not be placed as a model
            {"id": TERRAIN_ID, "name": "Bathymetry", "lon": ORIGIN[0], "lat": ORIGIN[1],
             "height": -1200.0},
        ]
        self.report_path = _write({})
        self.cfg_path = _write({
            "terrain_ion_asset_id": TERRAIN_ID,
            "manifest": _write(self.manifest),
            "report": self.report_path,
        })

    def report(self):
        with open(self.report_path) as fh:
            return json.load(fh)

    def models(self):
        return [a for a in fake_unreal._Level.actors
                if isinstance(a, fake_unreal.Cesium3DTileset) and a is not self.terrain]


class PopulateTest(_LevelFixture):
    """Placement and the height correction for standalone models."""

    def test_spawns_one_actor_per_model_and_skips_the_terrain(self):
        cesium_populate.run(self.cfg_path)
        labels = sorted(a.get_actor_label() for a in self.models())
        self.assertEqual(labels, ["Transect_01", "Transect_02", "Transect_03"])
        self.assertEqual(int(self.terrain.get_editor_property("ion_asset_id")), TERRAIN_ID)

    def test_rerun_is_idempotent(self):
        cesium_populate.run(self.cfg_path)
        first = len(fake_unreal._Level.actors)
        cesium_populate.run(self.cfg_path)
        self.assertEqual(len(fake_unreal._Level.actors), first)

    def test_georeference_origin_is_never_touched(self):
        cesium_populate.run(self.cfg_path)
        self.assertEqual(self.georef.origin, ORIGIN)

    def test_missing_georeference_is_a_hard_error(self):
        fake_unreal._Level.actors = [self.terrain]
        with self.assertRaises(RuntimeError):
            cesium_populate.run(self.cfg_path)

    # -- the height correction --------------------------------------------

    def test_offset_at_origin_is_purely_vertical(self):
        cesium_populate.run(self.cfg_path)
        a = next(a for a in self.models() if a.get_actor_label() == "Transect_01")
        # -1150 m -> -1200 m is a 50 m drop, in centimetres.
        self.assertAlmostEqual(a.location.z, -5000.0, delta=1.0)
        self.assertAlmostEqual(a.location.x, 0.0, delta=1.0)
        self.assertAlmostEqual(a.location.y, 0.0, delta=1.0)

    def test_offset_far_from_origin_follows_local_up_not_world_z(self):
        cesium_populate.run(self.cfg_path)
        a = next(a for a in self.models() if a.get_actor_label() == "Transect_02")
        site = next(m for m in self.manifest if m["id"] == 102)
        delta_cm = (-1200.0 - site["height"]) * 100.0     # -2000 cm

        # magnitude is preserved: the model moved exactly the height difference
        length = math.sqrt(a.location.x ** 2 + a.location.y ** 2 + a.location.z ** 2)
        self.assertAlmostEqual(length, abs(delta_cm), delta=1.0)

        # direction is the site's local up expressed in the origin's frame,
        # which at 50 km has a horizontal component a raw Z nudge would miss
        east, south, up = fake_unreal.esu_basis(site["lon"], site["lat"])
        oe, os_, ou = fake_unreal.esu_basis(*ORIGIN[:2])
        dot = lambda p, q: p[0] * q[0] + p[1] * q[1] + p[2] * q[2]
        expected = (delta_cm * dot(up, oe), delta_cm * dot(up, os_), delta_cm * dot(up, ou))
        self.assertAlmostEqual(a.location.x, expected[0], delta=1.0)
        self.assertAlmostEqual(a.location.y, expected[1], delta=1.0)
        self.assertAlmostEqual(a.location.z, expected[2], delta=1.0)
        self.assertGreater(abs(a.location.x), 1.0, "local up should tilt at 50 km")

    def test_unsampled_site_is_left_at_its_ion_height(self):
        cesium_populate.run(self.cfg_path)
        a = next(a for a in self.models() if a.get_actor_label() == "Transect_03")
        self.assertEqual((a.location.x, a.location.y, a.location.z), (0.0, 0.0, 0.0))
        row = next(r for r in self.report()["assets"] if r["id"] == 103)
        self.assertFalse(row["sampled"])
        self.assertEqual(row["placement"], "unsampled")
        self.assertEqual(row["delta_m"], 0.0)
        self.assertIsNone(row["terrain_height_m"])

    # -- the report --------------------------------------------------------

    def test_report_records_the_deltas_actually_applied(self):
        cesium_populate.run(self.cfg_path)
        rows = {r["id"]: r for r in self.report()["assets"]}
        self.assertAlmostEqual(rows[101]["delta_m"], -50.0, places=6)
        self.assertAlmostEqual(rows[102]["delta_m"], -20.0, places=6)
        self.assertEqual(self.report()["summary"]["anchored"], 2)

    def test_uniform_offset_is_called_out_as_a_datum_error(self):
        for n, m in enumerate(m for m in self.manifest if m["id"] != TERRAIN_ID):
            m["lat"] = ORIGIN[1] + 0.01 * n          # separate sites...
            m["lon"] = ORIGIN[0]
            m["height"] = -1163.0                    # ...sharing one height error
        self.cfg_path = _write({
            "terrain_ion_asset_id": TERRAIN_ID,
            "manifest": _write(self.manifest),
            "report": self.report_path,
        })
        cesium_populate.run(self.cfg_path)
        warnings = [m for lvl, m in fake_unreal.LOG if lvl == "warn"]
        self.assertTrue(any("datum offset" in w for w in warnings),
                        "a uniform shift should be flagged, not silently applied")

    def test_level_is_saved(self):
        cesium_populate.run(self.cfg_path)
        self.assertTrue(fake_unreal._Level.saved)


class ClusterStackTest(_LevelFixture):
    """Overlapping models stack instead of burying each other in one surface."""

    def cluster_manifest(self, gap=None, radius=50.0, stack=True):
        # Three models over the same patch of seafloor, at different depths.
        # Extents are deliberately asymmetric so a wrong one shows up.
        self.manifest = [
            {"id": 201, "name": "A_deep", "lon": ORIGIN[0], "lat": ORIGIN[1],
             "height": -1200.0, "height_min": -1210.0, "height_max": -1190.0,
             "radius_m": radius},
            {"id": 202, "name": "B_mid", "lon": ORIGIN[0], "lat": ORIGIN[1],
             "height": -1150.0, "height_min": -1160.0, "height_max": -1140.0,
             "radius_m": radius},
            {"id": 203, "name": "C_shallow", "lon": ORIGIN[0], "lat": ORIGIN[1],
             "height": -1100.0, "height_min": -1106.0, "height_max": -1094.0,
             "radius_m": radius},
        ]
        cfg = {"terrain_ion_asset_id": TERRAIN_ID,
               "manifest": _write(self.manifest), "report": self.report_path,
               "stack_clusters": stack}
        if gap is not None:
            cfg["stack_gap_m"] = gap
        self.cfg_path = _write(cfg)
        fake_unreal.TERRAIN_FN = lambda lon, lat: -1250.0

    def targets(self):
        return {r["id"]: r for r in self.report()["assets"]}

    def test_deepest_lands_on_terrain_and_the_rest_stack_on_it(self):
        self.cluster_manifest()
        cesium_populate.run(self.cfg_path)
        t = self.targets()

        # A is deepest (height_min -1210): its centre goes to the terrain.
        self.assertEqual(t[201]["placement"], "terrain")
        self.assertAlmostEqual(t[201]["target_height_m"], -1250.0, places=6)

        # B's bottom rests on A's top: -1250 + 10 = -1240, + B's 10 m below
        self.assertEqual(t[202]["placement"], "stacked")
        self.assertAlmostEqual(t[202]["target_height_m"], -1230.0, places=6)

        # C's bottom rests on B's top: -1230 + 10 = -1220, + C's 6 m below
        self.assertEqual(t[203]["placement"], "stacked")
        self.assertAlmostEqual(t[203]["target_height_m"], -1214.0, places=6)

    def test_stacked_models_do_not_overlap(self):
        self.cluster_manifest()
        cesium_populate.run(self.cfg_path)
        t = self.targets()
        src = {m["id"]: m for m in self.manifest}
        spans = []
        for i in (201, 202, 203):
            centre, m = t[i]["target_height_m"], src[i]
            spans.append((centre - (m["height"] - m["height_min"]),
                          centre + (m["height_max"] - m["height"])))
        spans.sort()
        for (_, top), (bottom, _) in zip(spans, spans[1:]):
            self.assertAlmostEqual(bottom, top, places=6,
                                   msg="stacked models should touch, not overlap")

    def test_gap_separates_the_stack(self):
        self.cluster_manifest(gap=5.0)
        cesium_populate.run(self.cfg_path)
        t = self.targets()
        self.assertAlmostEqual(t[201]["target_height_m"], -1250.0, places=6)
        self.assertAlmostEqual(t[202]["target_height_m"], -1225.0, places=6)
        self.assertAlmostEqual(t[203]["target_height_m"], -1204.0, places=6)

    def test_separate_footprints_are_each_snapped_to_terrain(self):
        self.cluster_manifest(radius=1.0)          # 1 m radii, all co-located...
        for n, m in enumerate(self.manifest):
            m["lat"] = ORIGIN[1] + 0.05 * n        # ...but now kilometres apart
        self.cfg_path = _write({"terrain_ion_asset_id": TERRAIN_ID,
                                "manifest": _write(self.manifest),
                                "report": self.report_path})
        cesium_populate.run(self.cfg_path)
        placements = {r["placement"] for r in self.report()["assets"]}
        self.assertEqual(placements, {"terrain"})

    def test_stacking_can_be_turned_off(self):
        self.cluster_manifest(stack=False)
        cesium_populate.run(self.cfg_path)
        placements = {r["placement"] for r in self.report()["assets"]}
        self.assertEqual(placements, {"terrain"},
                         "with stacking off every model snaps to the surface")

    def test_stacked_models_are_kept_out_of_the_datum_summary(self):
        self.cluster_manifest()
        cesium_populate.run(self.cfg_path)
        # Only the anchor carries datum evidence; the other two were positioned
        # by what sits under them, so counting them would fabricate a spread.
        self.assertEqual(self.report()["summary"]["anchored"], 1)

    def test_the_actor_is_actually_moved_to_its_stacked_height(self):
        self.cluster_manifest()
        cesium_populate.run(self.cfg_path)
        actor = next(a for a in self.models() if a.get_actor_label() == "B_mid")
        # -1150 -> -1230 is an 80 m drop, straight down at the origin.
        self.assertAlmostEqual(actor.location.z, -8000.0, delta=1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
