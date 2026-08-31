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
        self.terrain.set_editor_property("tileset_source",
                                         fake_unreal.TilesetSource.FROM_CESIUM_ION)
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


class SeafloorDatumTest(_LevelFixture):
    """The multibeam surface is the depth datum; relative depths are survey data."""

    FLOOR = -1250.0

    def build(self, models, terrain_fn=None, **cfg_extra):
        self.manifest = models
        cfg = {"terrain_ion_asset_id": TERRAIN_ID,
               "manifest": _write(self.manifest), "report": self.report_path}
        cfg.update(cfg_extra)
        self.cfg_path = _write(cfg)
        fake_unreal.TERRAIN_FN = terrain_fn or (lambda lon, lat: self.FLOOR)

    def rows(self):
        return {r["id"]: r for r in self.report()["assets"]}

    def seawall(self, radius=50.0):
        """A seafloor patch and two courses of a wall standing on it."""
        return [
            {"id": 301, "name": "floor_patch", "lon": ORIGIN[0], "lat": ORIGIN[1],
             "height": -1249.0, "height_min": -1251.0, "height_max": -1247.0,
             "radius_m": radius},
            {"id": 302, "name": "wall_lower", "lon": ORIGIN[0], "lat": ORIGIN[1],
             "height": -1245.0, "height_min": -1250.0, "height_max": -1240.0,
             "radius_m": radius},
            {"id": 303, "name": "wall_upper", "lon": ORIGIN[0], "lat": ORIGIN[1],
             "height": -1235.0, "height_min": -1240.0, "height_max": -1230.0,
             "radius_m": radius},
        ]

    # -- the point of the whole exercise -----------------------------------

    def test_relative_depths_survive_the_correction(self):
        models = self.seawall()
        self.build(models)
        cesium_populate.run(self.cfg_path)
        r = self.rows()
        before = {m["id"]: m["height"] for m in models}
        for a, b in ((301, 302), (302, 303), (301, 303)):
            self.assertAlmostEqual(
                r[a]["target_height_m"] - r[b]["target_height_m"],
                before[a] - before[b], places=6,
                msg="a seawall's height above the seafloor is measured, not an artefact")

    def test_one_shift_moves_the_whole_group(self):
        self.build(self.seawall())
        cesium_populate.run(self.cfg_path)
        deltas = {round(r["delta_m"], 9) for r in self.report()["assets"]}
        self.assertEqual(len(deltas), 1, "a rigid correction is one number per cluster")

    def test_the_binding_model_rests_on_the_seafloor(self):
        self.build(self.seawall())
        cesium_populate.run(self.cfg_path)
        r = self.rows()
        anchor = next(v for v in r.values() if v["placement"] == "anchor")
        self.assertEqual(anchor["id"], 301, "the most buried model is the binding one")
        self.assertAlmostEqual(anchor["base_above_seafloor_m"], 0.0, places=6)

    def test_nothing_is_left_below_the_seafloor(self):
        self.build(self.seawall())
        cesium_populate.run(self.cfg_path)
        for row in self.report()["assets"]:
            self.assertGreaterEqual(row["base_above_seafloor_m"], -1e-9,
                                    "%s ended up under the multibeam surface" % row["name"])

    def test_wall_height_above_the_seafloor_is_reported(self):
        self.build(self.seawall())
        cesium_populate.run(self.cfg_path)
        # wall_upper's base started 11 m above the floor patch's lowest point.
        self.assertAlmostEqual(self.rows()[303]["base_above_seafloor_m"], 11.0, places=6)

    # -- the max-lift rule, which is not the same as "deepest model" --------

    def test_the_binding_model_is_the_most_buried_not_the_deepest(self):
        # P is far deeper, but sits over deeper seafloor and clears it. Q is
        # shallower yet buried. Anchoring on P would leave Q 10 m underground.
        models = [
            {"id": 401, "name": "P_deep", "lon": ORIGIN[0], "lat": ORIGIN[1],
             "height": -1258.0, "height_min": -1260.0, "height_max": -1256.0,
             "radius_m": 500.0},
            {"id": 402, "name": "Q_buried", "lon": ORIGIN[0] + 0.001, "lat": ORIGIN[1],
             "height": -1238.0, "height_min": -1240.0, "height_max": -1236.0,
             "radius_m": 500.0},
        ]
        self.build(models, terrain_fn=lambda lon, lat:
                   -1265.0 if lon < ORIGIN[0] + 0.0005 else -1235.0)
        cesium_populate.run(self.cfg_path)
        r = self.rows()
        self.assertEqual(r[402]["placement"], "anchor")
        self.assertEqual(r[401]["placement"], "offset")
        self.assertAlmostEqual(r[402]["base_above_seafloor_m"], 0.0, places=6)
        self.assertAlmostEqual(r[401]["base_above_seafloor_m"], 10.0, places=6)

    # -- clearance, carrying, and the escape hatches ------------------------

    def test_clearance_lifts_the_group_clear_of_the_surface(self):
        self.build(self.seawall(), seafloor_clearance_m=0.25)
        cesium_populate.run(self.cfg_path)
        for row in self.report()["assets"]:
            self.assertGreaterEqual(row["base_above_seafloor_m"], 0.25 - 1e-9)

    def test_a_member_with_no_terrain_is_carried_by_its_cluster(self):
        models = self.seawall()
        # ~33 m north: outside terrain coverage, still inside the 100 m
        # footprint reach, so it stays in the cluster.
        models[2]["lat"] = ORIGIN[1] + 0.0003
        self.build(models, terrain_fn=lambda lon, lat:
                   None if lat > ORIGIN[1] + 0.0002 else self.FLOOR)
        cesium_populate.run(self.cfg_path)
        r = self.rows()
        self.assertEqual(r[303]["placement"], "carried")
        self.assertAlmostEqual(r[303]["delta_m"], r[301]["delta_m"], places=9,
                               msg="a carried model still gets its cluster's datum fix")

    def test_a_cluster_with_no_terrain_at_all_is_left_alone(self):
        self.build(self.seawall(), terrain_fn=lambda lon, lat: None)
        cesium_populate.run(self.cfg_path)
        for row in self.report()["assets"]:
            self.assertEqual(row["placement"], "unsampled")
            self.assertEqual(row["delta_m"], 0.0)

    def test_the_summary_counts_one_correction_per_cluster(self):
        self.build(self.seawall())
        cesium_populate.run(self.cfg_path)
        self.assertEqual(self.report()["summary"]["anchored"], 1)

    def test_separate_footprints_are_corrected_independently(self):
        models = self.seawall(radius=1.0)
        for n, m in enumerate(models):
            m["lat"] = ORIGIN[1] + 0.05 * n
        self.build(models)
        cesium_populate.run(self.cfg_path)
        placements = [r["placement"] for r in self.report()["assets"]]
        self.assertEqual(placements, ["anchor"] * 3)

    def test_clustering_can_be_turned_off(self):
        self.build(self.seawall(), cluster_models=False)
        cesium_populate.run(self.cfg_path)
        placements = {r["placement"] for r in self.report()["assets"]}
        self.assertEqual(placements, {"anchor"},
                         "with clustering off each model is corrected alone")

    def test_the_actor_is_moved_by_the_cluster_delta(self):
        self.build(self.seawall())
        cesium_populate.run(self.cfg_path)
        delta = self.rows()[302]["delta_m"]
        actor = next(a for a in self.models() if a.get_actor_label() == "wall_lower")
        self.assertAlmostEqual(actor.location.z, delta * 100.0, delta=1.0)


class PreflightTest(_LevelFixture):
    """Preflight must diagnose, not just fail — and must change nothing."""

    def setUp(self):
        _LevelFixture.setUp(self)
        os.environ["CESIUM_ION_TOKEN"] = "not-a-real-token"
        # The base fixture is built to exercise failure paths — a site far
        # outside terrain coverage, no extents. Preflight correctly rejects it,
        # so the passing case needs a manifest that is actually in good shape.
        self.manifest = [
            {"id": 101, "name": "Transect_01", "lon": ORIGIN[0], "lat": ORIGIN[1],
             "height": -1150.0, "height_min": -1152.0, "height_max": -1148.0,
             "radius_m": 20.0},
            {"id": 102, "name": "Transect_02", "lon": ORIGIN[0] + 0.01,
             "lat": ORIGIN[1], "height": -1160.0, "height_min": -1162.0,
             "height_max": -1158.0, "radius_m": 20.0},
        ]
        self.cfg_path = _write({"terrain_ion_asset_id": TERRAIN_ID,
                                "manifest": _write(self.manifest),
                                "report": self.report_path})

    def logs(self):
        return "\n".join(m for _, m in fake_unreal.LOG)

    def test_passes_on_a_correctly_set_up_level(self):
        self.assertTrue(cesium_populate.preflight(self.cfg_path))
        self.assertIn("preflight passed", self.logs())

    def test_changes_nothing(self):
        before = len(fake_unreal._Level.actors)
        cesium_populate.preflight(self.cfg_path)
        self.assertEqual(len(fake_unreal._Level.actors), before)
        self.assertFalse(fake_unreal._Level.saved)

    def test_missing_georeference_is_named(self):
        fake_unreal._Level.actors = [self.terrain]
        self.assertFalse(cesium_populate.preflight(self.cfg_path))
        self.assertIn("CesiumGeoreference", self.logs())

    def test_missing_token_is_named(self):
        del os.environ["CESIUM_ION_TOKEN"]
        self.assertFalse(cesium_populate.preflight(self.cfg_path))
        self.assertIn("CESIUM_ION_TOKEN set", self.logs())

    def test_missing_sampler_binding_is_named(self):
        saved = fake_unreal.CesiumSampleHeightMostDetailedAsyncAction
        del fake_unreal.CesiumSampleHeightMostDetailedAsyncAction
        try:
            self.assertFalse(cesium_populate.preflight(self.cfg_path))
            self.assertIn("height sampler binding", self.logs())
        finally:
            fake_unreal.CesiumSampleHeightMostDetailedAsyncAction = saved

    def test_a_manifest_without_extents_is_flagged(self):
        # Manifests from before footprints existed cannot cluster.
        stripped = [{k: v for k, v in m.items() if k != "height_min"}
                    for m in self.manifest]
        self.cfg_path = _write({"terrain_ion_asset_id": TERRAIN_ID,
                                "manifest": _write(stripped),
                                "report": self.report_path})
        cesium_populate.preflight(self.cfg_path)
        self.assertIn("manifest carries extents", self.logs())

    def test_sites_far_from_the_origin_are_flagged(self):
        far = [dict(m, lat=0.0, lon=0.0) for m in self.manifest]
        self.cfg_path = _write({"terrain_ion_asset_id": TERRAIN_ID,
                                "manifest": _write(far), "report": self.report_path})
        self.assertFalse(cesium_populate.preflight(self.cfg_path))
        self.assertIn("precision degrades", self.logs())


class DepthAnchorTest(_LevelFixture):
    """The anchor estimator is a seam; an unknown name must not silently pass."""

    def test_unknown_anchor_is_rejected(self):
        self.cfg_path = _write({"terrain_ion_asset_id": TERRAIN_ID,
                                "manifest": _write(self.manifest),
                                "report": self.report_path,
                                "depth_anchor": "surface_percentile"})
        with self.assertRaises(RuntimeError) as caught:
            cesium_populate.run(self.cfg_path)
        self.assertIn("bounding_volume", str(caught.exception))

    def test_the_default_anchor_is_the_bounding_volume(self):
        self.assertIs(cesium_populate.DEPTH_ANCHORS["bounding_volume"],
                      cesium_populate.bounding_volume_lift)
        self.assertAlmostEqual(
            cesium_populate.bounding_volume_lift(
                {"height": -1249.0, "height_min": -1251.0}, -1250.0),
            1.0, places=9)

    def test_a_group_correction_that_disagrees_is_flagged(self):
        # Five separate sites, one with a bad height_min dragging its lift.
        models = []
        for n in range(5):
            models.append({"id": 500 + n, "name": "site_%d" % n,
                           "lon": ORIGIN[0], "lat": ORIGIN[1] + 0.05 * n,
                           "height": -1200.0,
                           "height_min": -1400.0 if n == 3 else -1202.0,
                           "radius_m": 1.0})
        self.cfg_path = _write({"terrain_ion_asset_id": TERRAIN_ID,
                                "manifest": _write(models), "report": self.report_path})
        fake_unreal.TERRAIN_FN = lambda lon, lat: -1250.0
        cesium_populate.run(self.cfg_path)
        outliers = self.report()["summary"].get("outliers", [])
        self.assertEqual([o["name"] for o in outliers], ["site_3"])
        self.assertIn("stray vertex", self.logs())

    def logs(self):
        return "\n".join(m for _, m in fake_unreal.LOG)



if __name__ == "__main__":
    unittest.main(verbosity=2)
