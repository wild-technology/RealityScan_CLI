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


class TestAttributionWithDuplicates(unittest.TestCase):
    """Copy-layout overlap images live in two zones, so two inputs share
    basenames. RealityScan has been seen to keep BOTH copies (NA173 F2,
    2026-09-06: 78 + 80 with 21 shared peeled as 158) and to fold them
    into one camera (H2063, another session: 400 + 360 with 4 shared
    peeled as 756). Both are lossless; before 2026-09-06 the second read
    as a loss of exactly the duplicate count and was rejected."""

    @staticmethod
    def pair(n_a, n_b, shared, za='z3', zb='z7'):
        a_imgs = [f'a_{i}.jpg' for i in range(n_a)]
        b_imgs = a_imgs[:shared] + [f'b_{i}.jpg' for i in range(n_b - shared)]
        return (mk(za, 'c0', n_a, None, images=a_imgs),
                mk(zb, 'c0', n_b, None, images=b_imgs))

    def test_both_copies_kept_is_exact_sum(self):
        # NA173 F2: 78 + 80 with 21 shared -> peel [158, 80, 78]
        a, b = self.pair(78, 80, 21, 'zone_1', 'zone_2')
        res, conf = merge_zones.attribute_result([a, b], [158, 80, 78], logger)
        self.assertEqual(conf, 'count_only')
        self.assertEqual(res[0]['inputs'], ['zone_1/c0', 'zone_2/c0'])
        self.assertEqual((res[0]['estimated_loss'], res[0]['estimated_collapsed']), (0, 0))
        self.assertIsNone(res[0]['members'])
        self.assertTrue(res[1]['residual'] and res[2]['residual'])

    def test_folded_duplicates_are_a_lossless_fusion(self):
        # H2063 zone_3/3 + zone_7/1: sum 760, unique 756, peel 756
        a, b = self.pair(400, 360, 4)
        res, conf = merge_zones.attribute_result([a, b], [756, 400, 360], logger)
        self.assertEqual(conf, 'count_only')
        self.assertEqual(res[0]['inputs'], ['z3/c0', 'z7/c0'])
        self.assertEqual((res[0]['estimated_loss'], res[0]['estimated_collapsed']), (0, 4))
        self.assertIsNone(res[0]['members'])

    def test_heavy_overlap_folded(self):
        # H2063 zone_3/3 + zone_7/2: sum 743, unique 541, peel 541
        a, b = self.pair(500, 243, 202)
        res, conf = merge_zones.attribute_result([a, b], [541], logger)
        self.assertEqual(conf, 'count_only')
        self.assertEqual((res[0]['estimated_loss'], res[0]['estimated_collapsed']), (0, 202))

    def test_real_loss_below_unique_needs_tolerance(self):
        # H2063 zone_2/8 + zone_5/4: sum 1488, unique 1248, peel 1240
        a, b = self.pair(800, 688, 240, 'z2', 'z5')
        res, conf = merge_zones.attribute_result([a, b], [1240], logger)
        self.assertEqual(conf, 'ambiguous')       # 8 cameras really lost, no budget
        self.assertIsNone(res[0]['members'])
        res, conf = merge_zones.attribute_result([a, b], [1240], logger,
                                                 loss_tolerance=8)
        self.assertEqual(conf, 'count_only')
        self.assertEqual((res[0]['estimated_loss'], res[0]['estimated_collapsed']), (8, 240))

    def test_same_zone_loss_is_still_a_loss(self):
        # H2063 zone_5/5 + zone_5/9: no shared images, 1110 -> 1029
        a, b = self.pair(555, 555, 0, 'z5', 'z5b')
        res, conf = merge_zones.attribute_result([a, b], [1029], logger)
        self.assertEqual(conf, 'ambiguous')
        res, conf = merge_zones.attribute_result([a, b], [1029], logger,
                                                 loss_tolerance=81)
        self.assertEqual((res[0]['estimated_loss'], res[0]['estimated_collapsed']), (81, 0))

    def test_partial_fold_is_only_a_candidate_and_warned(self):
        a, b = self.pair(100, 100, 10)         # sum 200, unique 190
        with self.assertLogs(logger, level='WARNING') as cm:
            res, conf = merge_zones.attribute_result([a, b], [195], logger)
        self.assertEqual(conf, 'count_only')
        self.assertEqual((res[0]['estimated_loss'], res[0]['estimated_collapsed']), (0, 5))
        self.assertTrue(any('indistinguishable' in m for m in cm.output))

    def test_lone_input_is_not_mistaken_for_a_folded_pair(self):
        # A single 100-camera input and a 100+20 pair sharing 20: a peel of
        # 100 reads as the lone input AND as the folded pair - ambiguous,
        # never silently one of them.
        a, b = self.pair(100, 20, 20, 'z1', 'z2')
        c = mk('z9', 'c0', 100, None)
        res, conf = merge_zones.attribute_result([a, b, c], [100, 100, 20], logger)
        self.assertEqual(conf, 'ambiguous')

    def test_manifest_without_images_keeps_the_sum_rule(self):
        a = mk('z1', 'c0', 78, None)
        a['images'] = []
        b = mk('z2', 'c0', 42, None)
        b['images'] = []
        res, conf = merge_zones.attribute_result([a, b], [120], logger)
        self.assertEqual(conf, 'count_only')
        self.assertEqual(res[0]['inputs'], ['z1/c0', 'z2/c0'])


class TestAttribution(unittest.TestCase):
    def test_exact_fusion(self):
        a = mk('z1', 'c0', 78, None)
        b = mk('z2', 'c0', 42, None)
        res, conf = merge_zones.attribute_result([a, b], [120], logger)
        self.assertEqual(conf, 'count_only')
        self.assertEqual(res[0]['inputs'], ['z1/c0', 'z2/c0'])
        self.assertIsNone(res[0]['members'])

    def test_no_fusion_identity(self):
        a = mk('z1', 'c0', 78, None)
        b = mk('z2', 'c0', 42, None)
        res, conf = merge_zones.attribute_result([a, b], [78, 42], logger)
        self.assertEqual(conf, 'count_only')
        self.assertEqual([r['inputs'] for r in res], [['z1/c0'], ['z2/c0']])

    def test_partial_fusion(self):
        a = mk('z1', 'c0', 100, None)
        b = mk('z1', 'c1', 60, None)
        c = mk('z2', 'c0', 40, None)
        res, conf = merge_zones.attribute_result([a, b, c], [140, 60], logger)
        self.assertEqual(conf, 'count_only')
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
        self.assertEqual(conf, 'count_only')
        self.assertEqual(res[0]['inputs'], ['z1/c0', 'z2/c0'])
        self.assertFalse(res[0]['residual'])
        self.assertIsNone(res[0]['members'])
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


if __name__ == '__main__':
    unittest.main()
