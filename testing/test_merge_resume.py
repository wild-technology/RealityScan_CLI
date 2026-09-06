"""merge_zones resume: reuse converged clusters, refuse anything else.

A cross-zone merge costs hours per cluster. NA165/H2063 lost a 12 h run to a
harness restart with three clusters already converged on disk, and merge_zones
had no way to pick them up - a plain restart would have re-merged all 40
inputs. These tests pin the four decisions that make resume safe rather than
merely fast:

  1. a converged cluster whose files exist IS reused;
  2. a cluster that had NOT converged is NOT reused - it was mid-ladder when
     the run died, so its record describes unfinished work;
  3. a report describing a DIFFERENT question (other ladder / gate / inputs)
     is refused outright rather than blended into this one;
  4. a converged cluster whose .rsalign has since vanished is re-merged, not
     carried forward to fail hours later in the assembly complist.
"""
import json
import logging
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import merge_zones  # noqa: E402


def _fp(inputs=('z/A', 'z/B'), ladder='merge_first', pair_gate='overlap'):
    return merge_zones.run_fingerprint(
        list(inputs), ladder, 'neighbour', pair_gate, 0.0, 50, False)


class MergeResumeTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.log = logging.getLogger('test_merge_resume')
        self.log.addHandler(logging.NullHandler())
        # A real file, so the existence check has something to find.
        self.rsalign = os.path.join(self.dir, 'c0.rsalign')
        with open(self.rsalign, 'w', encoding='utf-8') as fh:
            fh.write('x')

    def _write(self, clusters, fingerprint=None):
        report = {'schema': 2, 'clusters': clusters}
        if fingerprint is not None:
            report['run_fingerprint'] = fingerprint
        with open(os.path.join(self.dir, 'merge_report.json'), 'w',
                  encoding='utf-8') as fh:
            json.dump(report, fh)

    def _cluster(self, converged=True, rsalign=None, inputs=('z/A', 'z/B')):
        return {
            'cluster': 'cluster_0',
            'inputs': list(inputs),
            'converged': converged,
            'final_components': [
                {'key': 'merged', 'rsalign': rsalign or self.rsalign,
                 'camera_count': 10},
            ],
        }

    def test_converged_cluster_is_reused(self):
        self._write([self._cluster()], _fp())
        got = merge_zones.load_resumable_clusters(self.dir, _fp(), self.log)
        self.assertEqual(len(got), 1)
        self.assertIn(frozenset({'z/A', 'z/B'}), got)

    def test_unconverged_cluster_is_not_reused(self):
        """It was mid-ladder when the run died; its work is unfinished."""
        self._write([self._cluster(converged=False)], _fp())
        got = merge_zones.load_resumable_clusters(self.dir, _fp(), self.log)
        self.assertEqual(got, {})

    def test_different_question_is_refused(self):
        """A different ladder repartitions and re-decides; do not blend runs."""
        self._write([self._cluster()], _fp(ladder='content_first'))
        got = merge_zones.load_resumable_clusters(self.dir, _fp(), self.log)
        self.assertEqual(got, {})

    def test_different_inputs_are_refused(self):
        self._write([self._cluster()], _fp(inputs=('z/A', 'z/B', 'z/C')))
        got = merge_zones.load_resumable_clusters(self.dir, _fp(), self.log)
        self.assertEqual(got, {})

    def test_input_order_does_not_matter(self):
        """Order does not affect partitioning, so it must not block resume."""
        self._write([self._cluster()], _fp(inputs=('z/B', 'z/A')))
        got = merge_zones.load_resumable_clusters(self.dir, _fp(), self.log)
        self.assertEqual(len(got), 1)

    def test_missing_component_file_forces_remerge(self):
        """A carried record whose file is gone would fail in the assembly."""
        self._write([self._cluster(rsalign=os.path.join(self.dir, 'gone.rsalign'))],
                    _fp())
        got = merge_zones.load_resumable_clusters(self.dir, _fp(), self.log)
        self.assertEqual(got, {})

    def test_report_without_fingerprint_is_refused(self):
        """Pre-fingerprint reports cannot be shown to describe the same run."""
        self._write([self._cluster()], None)
        got = merge_zones.load_resumable_clusters(self.dir, _fp(), self.log)
        self.assertEqual(got, {})

    def test_no_report_is_not_an_error(self):
        got = merge_zones.load_resumable_clusters(self.dir, _fp(), self.log)
        self.assertEqual(got, {})

    def test_corrupt_report_starts_fresh(self):
        with open(os.path.join(self.dir, 'merge_report.json'), 'w',
                  encoding='utf-8') as fh:
            fh.write('{not json')
        got = merge_zones.load_resumable_clusters(self.dir, _fp(), self.log)
        self.assertEqual(got, {})

    def test_fingerprint_ignores_input_order_only(self):
        """Sanity: the fingerprint still distinguishes the things that matter."""
        base = _fp()
        self.assertEqual(base, _fp(inputs=('z/B', 'z/A')))
        self.assertNotEqual(base, _fp(pair_gate='border'))
        self.assertNotEqual(base, _fp(ladder='content_first'))


if __name__ == '__main__':
    unittest.main()
