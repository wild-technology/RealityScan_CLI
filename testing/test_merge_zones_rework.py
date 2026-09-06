"""Unit tests for the feature-aware merge driver's pure logic
(merge_zones.py rework, 2026-07-24): cluster partitioning, count
attribution, and peel-count reading. No RealityScan interaction."""
import json
import logging
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

import merge_zones
from modules import component_manifest

logger = logging.getLogger('test_merge_rework')


def mk(zone, comp, count, bbox, images=None):
    # image basenames must be globally unique per (zone, comp) fixture -
    # identical names across zones read as overlap-band twins.
    return {
        'schema': 1, 'zone': zone, 'component': comp,
        'rsalign': f'D:/fake/{zone}/{comp}.rsalign',
        'images': images or [f'{zone}_{comp}_{i}.jpg' for i in range(count)],
        'camera_count': count, 'bbox_utm': bbox,
        'quality': {'mean_reproj_px': None},
    }


class TestPartitionClusters(unittest.TestCase):
    def test_bow_hull_pocket_partition(self):
        # Mirrors the real H2023 geography: hull band, bow ~60 m away,
        # pocket further west. Hull comps chain via overlapping boxes.
        hull_a = mk('zone_1', 'c0', 1600, [594693, 2345108, 594718, 2345160])
        hull_b = mk('zone_1', 'c1', 941, [594704, 2345096, 594719, 2345127])
        bow = mk('zone_2', 'c0', 686, [594653, 2345217, 594668, 2345251])
        pocket = mk('zone_2', 'c2', 102, [594599, 2345248, 594607, 2345256])
        clusters, plan = merge_zones.partition_clusters(
            [hull_a, hull_b, bow, pocket], logger)
        sizes = sorted(len(c) for c in clusters)
        self.assertEqual(sizes, [1, 1, 2])
        # largest cluster first (by camera sum)
        self.assertEqual(len(clusters[0]), 2)
        keys = {m['component'] for m in clusters[0]}
        self.assertEqual(keys, {'c0', 'c1'})

    def test_twin_dropped_before_clustering(self):
        keeper = mk('zone_2', 'c0', 686, [594653, 2345217, 594668, 2345251])
        twin = mk('zone_1', 'c2', 672, [594653, 2345217, 594668, 2345251],
                  images=keeper['images'][:672])  # fully contained
        clusters, plan = merge_zones.partition_clusters([keeper, twin], logger)
        self.assertEqual(plan['discards'], ['zone_1/c2'])
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0]), 1)
        self.assertEqual(clusters[0][0]['component'], 'c0')

    def test_null_bbox_pairs_with_everything(self):
        a = mk('zone_1', 'c0', 100, [0, 0, 10, 10])
        b = mk('zone_2', 'c0', 100, None)
        far = mk('zone_3', 'c0', 100, [10000, 10000, 10010, 10010])
        clusters, _ = merge_zones.partition_clusters([a, b, far], logger)
        # null bbox borders everything -> one cluster of 3
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0]), 3)


class TestAttribution(unittest.TestCase):
    def test_exact_fusion(self):
        a = mk('z1', 'c0', 78, None)
        b = mk('z2', 'c0', 42, None)
        res, conf = merge_zones.attribute_result([a, b], [120], logger)
        self.assertEqual(conf, 'exact')
        self.assertEqual(res[0]['inputs'], ['z1/c0', 'z2/c0'])
        self.assertEqual(len(res[0]['members']), 120)

    def test_no_fusion_identity(self):
        a = mk('z1', 'c0', 78, None)
        b = mk('z2', 'c0', 42, None)
        res, conf = merge_zones.attribute_result([a, b], [78, 42], logger)
        self.assertEqual(conf, 'exact')
        self.assertEqual([r['inputs'] for r in res], [['z1/c0'], ['z2/c0']])

    def test_partial_fusion(self):
        a = mk('z1', 'c0', 100, None)
        b = mk('z1', 'c1', 60, None)
        c = mk('z2', 'c0', 40, None)
        res, conf = merge_zones.attribute_result([a, b, c], [140, 60], logger)
        self.assertEqual(conf, 'exact')
        self.assertEqual(res[0]['inputs'], ['z1/c0', 'z2/c0'])
        self.assertEqual(res[1]['inputs'], ['z1/c1'])

    def test_ambiguous_flagged(self):
        # two equal-size inputs, one fused pair: subset-sum is ambiguous
        a = mk('z1', 'c0', 50, None)
        b = mk('z1', 'c1', 50, None)
        c = mk('z2', 'c0', 50, None)
        res, conf = merge_zones.attribute_result([a, b, c], [100, 50], logger)
        self.assertEqual(conf, 'ambiguous')
        # every peel count still gets a (best-effort) attribution
        self.assertEqual([r['camera_count'] for r in res], [100, 50])

    def test_unattributable_count(self):
        a = mk('z1', 'c0', 78, None)
        res, conf = merge_zones.attribute_result([a], [50], logger)
        self.assertEqual(conf, 'ambiguous')
        self.assertIsNone(res[0]['members'])

    def test_residual_sources_detected(self):
        # CLI fact (smoke E2E 2026-07-24): the fused component coexists
        # with its source components in the scene - peel [120, 78, 42]
        # from inputs 78+42. Sources = residuals, never adopted.
        a = mk('z1', 'c0', 78, None)
        b = mk('z2', 'c0', 42, None)
        res, conf = merge_zones.attribute_result([a, b], [120, 78, 42], logger)
        self.assertEqual(conf, 'exact')
        self.assertEqual(res[0]['inputs'], ['z1/c0', 'z2/c0'])
        self.assertFalse(res[0]['residual'])
        self.assertEqual(len(res[0]['members']), 120)
        self.assertTrue(res[1]['residual'])
        self.assertTrue(res[2]['residual'])
        self.assertEqual([r['peel_index'] for r in res], [0, 1, 2])
        adopted = [r for r in res if r['inputs']]
        self.assertEqual(len(adopted), 1)


class TestPeelCounts(unittest.TestCase):
    def test_reads_per_component_counts(self):
        with tempfile.TemporaryDirectory() as td:
            for k, n in enumerate([120, 36]):
                d = os.path.join(td, f'identity_r{k}')
                os.makedirs(d)
                for i in range(n):
                    open(os.path.join(d, f'{i:05d}.xmp'), 'w').close()
            os.makedirs(os.path.join(td, 'identity_r2'))  # empty terminal
            self.assertEqual(merge_zones.peel_counts_from(td), [120, 36])

    def test_no_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(merge_zones.peel_counts_from(td), [])


class TestLoadInputs(unittest.TestCase):
    def test_complist_requires_manifests(self):
        with tempfile.TemporaryDirectory() as td:
            rsalign = os.path.join(td, 'zone_x', 'zone_x_c0.rsalign')
            os.makedirs(os.path.dirname(rsalign))
            open(rsalign, 'w').close()
            complist = os.path.join(td, 'in.complist')
            with open(complist, 'w') as f:
                f.write(rsalign + '\n')
            with self.assertRaises(ValueError):
                merge_zones.load_inputs(td, complist, logger)

    def test_complist_with_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            rsalign = os.path.join(td, 'zone_x', 'zone_x_c0.rsalign')
            os.makedirs(os.path.dirname(rsalign))
            open(rsalign, 'w').close()
            m = component_manifest.build_manifest(
                'zone_x', 'zone_x_c0', rsalign, ['a.jpg', 'b.jpg'])
            component_manifest.write_manifest(m)
            complist = os.path.join(td, 'in.complist')
            with open(complist, 'w') as f:
                f.write(rsalign + '\n')
            picked = merge_zones.load_inputs(td, complist, logger)
            self.assertEqual(len(picked), 1)
            self.assertEqual(picked[0]['component'], 'zone_x_c0')


class TestAttributionUniqueUnion(unittest.TestCase):
    """Cross-zone fusions peel as the UNIQUE image union, not the camera sum.

    The batcher copies every overlap image into each zone it touches, so two
    zones' components hold the same basenames at different paths, and
    RealityScan 2.2 fuses by image content (D7) and collapses them. Every
    number below is measured from NA165/H2063 on 2026-09-06, where the old
    sum-based arithmetic rejected three lossless cross-zone fusions.
    """

    @staticmethod
    def _pair(shared, own_a, own_b, za='zone_3', ca='c3', zb='zone_7', cb='c2'):
        s = [f'shared_{i}.jpg' for i in range(shared)]
        a = mk(za, ca, shared + own_a, None,
               images=s + [f'{za}_{ca}_own_{i}.jpg' for i in range(own_a)])
        b = mk(zb, cb, shared + own_b, None,
               images=s + [f'{zb}_{cb}_own_{i}.jpg' for i in range(own_b)])
        return a, b

    def test_perfect_cross_zone_fusion_is_exact_on_union(self):
        # zone_3/C3 206 + zone_7/C2 537, 202 shared -> union 541; RS peeled
        # 541 alongside both sources. Sum-based code rejected this.
        a, b = self._pair(202, 4, 335)
        res, conf = merge_zones.attribute_result([a, b], [541, 206, 537], logger)
        self.assertEqual(conf, 'exact')
        self.assertEqual(res[0]['inputs'], ['zone_3/c3', 'zone_7/c2'])
        self.assertEqual(len(res[0]['members']), 541)
        self.assertEqual(res[0]['loss'], 0)
        self.assertTrue(res[1]['residual'])
        self.assertTrue(res[2]['residual'])

    def test_small_duplicate_count_still_exact(self):
        # zone_3/C3 206 + zone_7/C1 554, 4 shared -> union 756, peel 756.
        a, b = self._pair(4, 202, 550, zb='zone_7', cb='c1')
        res, conf = merge_zones.attribute_result([a, b], [756], logger)
        self.assertEqual(conf, 'exact')
        self.assertEqual(res[0]['inputs'], ['zone_3/c3', 'zone_7/c1'])

    def test_sum_of_camera_counts_is_no_longer_a_match(self):
        # 743 is the camera SUM. A content fusion never peels as that, so it
        # must not be attributed as one - that was the old false positive.
        a, b = self._pair(202, 4, 335)
        res, conf = merge_zones.attribute_result([a, b], [743], logger)
        self.assertEqual(conf, 'ambiguous')
        self.assertEqual(res[0]['inputs'], [])

    def test_real_loss_is_measured_against_union_not_sum(self):
        # zone_2/C8 464 + zone_5/C4 1024, 240 shared -> union 1248. RS peeled
        # 1240: 8 genuinely shed cameras, NOT the 248 the sum implied.
        a, b = self._pair(240, 224, 784, za='zone_2', ca='c8', zb='zone_5', cb='c4')
        res, conf = merge_zones.attribute_result([a, b], [1240], logger,
                                                 loss_tolerance=8)
        self.assertEqual(conf, 'exact')
        self.assertEqual(res[0]['inputs'], ['zone_2/c8', 'zone_5/c4'])
        self.assertEqual(res[0]['loss'], 8)
        # and with no budget it is correctly refused
        res, conf = merge_zones.attribute_result([a, b], [1240], logger)
        self.assertEqual(conf, 'ambiguous')

    def test_same_zone_disjoint_inputs_unchanged(self):
        # No shared basenames -> union == sum, identical to the old behaviour.
        a = mk('z1', 'c0', 78, None)
        b = mk('z1', 'c1', 42, None)
        res, conf = merge_zones.attribute_result([a, b], [120, 78, 42], logger)
        self.assertEqual(conf, 'exact')
        self.assertEqual(res[0]['inputs'], ['z1/c0', 'z1/c1'])


if __name__ == '__main__':
    unittest.main()
