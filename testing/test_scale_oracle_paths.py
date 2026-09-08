"""scale_oracle must find an identity record in BOTH layouts that produce one.

The two producers put their identity records in different places, and callers
hand `component_position_cloud` the directory holding the .rsalign for both:

    AlignZone.bat            <zone>/identity/<c>.csv
                             <zone>/latest_components/<c>.rsalign   <- SIBLING
    MergeZoneComponents.bat  <attempt>/identity_r0/
                             <attempt>/<c>.rsalign                  <- beside

So an unfused zone component's CSV sits one level ABOVE the directory holding
its mesh export. Looking only beside it found nothing, every input scored
'unmeasured', and because 'unmeasured' silently disarms the deliverable gate
rather than failing it, nothing pointed at the missing directory (NA165/H2063,
2026-09-07).
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import scale_oracle  # noqa: E402

CSV = ("#cameras 3\n"
       "#name,x,y,z,yaw,pitch,roll,focal,k1,k2\n"
       "a.jpg,1.0,2.0,3.0,0,0,0,28,0,0\n"
       "b.jpg,4.0,5.0,6.0,0,0,0,28,0,0\n"
       "c.jpg,7.0,8.0,9.0,0,0,0,28,0,0\n")


class ScaleOraclePathTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def _csv(self, folder, name):
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, name + ".csv"), "w",
                  encoding="utf-8") as fh:
            fh.write(CSV)

    def test_csv_beside_the_export(self):
        """The fused case: identity/ sits in the same directory."""
        comp = os.path.join(self.root, "attempt_1")
        self._csv(os.path.join(comp, "identity"), "cluster_0_a1_c0")
        got = scale_oracle.component_position_cloud(comp, "cluster_0_a1_c0")
        self.assertEqual(len(got), 3)

    def test_csv_one_level_up(self):
        """The zone-align case that was broken: identity/ is a SIBLING of
        latest_components/, so it is one level above the .rsalign."""
        zone = os.path.join(self.root, "zone_1")
        self._csv(os.path.join(zone, "identity"), "Component 0")
        exports = os.path.join(zone, "latest_components")
        os.makedirs(exports, exist_ok=True)
        got = scale_oracle.component_position_cloud(exports, "Component 0")
        self.assertEqual(len(got), 3,
                         "a zone component's CSV lives one level above its "
                         "export directory; missing it scores every input "
                         "'unmeasured' and silently disarms the scale gate")

    def test_beside_wins_over_parent(self):
        """A record beside the export is the component's own; prefer it."""
        zone = os.path.join(self.root, "zone_2")
        exports = os.path.join(zone, "latest_components")
        self._csv(os.path.join(zone, "identity"), "Component 1")       # parent
        os.makedirs(exports, exist_ok=True)
        with open(os.path.join(exports, "identity", "Component 1.csv")
                  if os.path.isdir(os.path.join(exports, "identity"))
                  else self._mk(exports, "Component 1"), "w",
                  encoding="utf-8") as fh:
            fh.write(CSV.replace("#cameras 3", "#cameras 2")
                     .replace("c.jpg,7.0,8.0,9.0,0,0,0,28,0,0\n", ""))
        got = scale_oracle.component_position_cloud(exports, "Component 1")
        self.assertEqual(len(got), 2, "the record beside the export wins")

    @staticmethod
    def _mk(exports, name):
        os.makedirs(os.path.join(exports, "identity"), exist_ok=True)
        return os.path.join(exports, "identity", name + ".csv")

    def test_missing_everywhere_is_empty_not_an_error(self):
        exports = os.path.join(self.root, "zone_3", "latest_components")
        os.makedirs(exports, exist_ok=True)
        self.assertEqual(
            scale_oracle.component_position_cloud(exports, "Component 9"), [])


if __name__ == "__main__":
    unittest.main()
