"""
The dated project copy must be sized against the actual project, not a fixed
threshold.

run_models ends with a dated RC_projects copy that duplicates the WHOLE
project. Two NA165/H2060 incidents (2026-09-01) shaped this guard:

1. It ran immediately after the loop aborted on the 50 GB disk floor: at
   32 GB free it tried to write a 31.8 GB duplicate, hit 0x80070070
   ERROR_DISK_FULL and took C: to 0.01 GB.
2. With 157 GB free - comfortably past 2x the floor - it wrote a 119.5 GB
   duplicate, leaving 43 GB and starving the export stage that followed.

A fixed threshold only asks "is there room to start", never "is there room to
finish". project_size_gb answers the second question.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run_models import MIN_FREE_GB, project_size_gb


def test_size_counts_the_sibling_data_dir_not_just_the_rsproj(tmp_path):
    # The .rsproj is ~1 MB; the bulk lives beside it in a folder of the same
    # stem, which is exactly why the .rsproj size tells you nothing.
    proj = tmp_path / "Assembly.rsproj"
    proj.write_bytes(b"x" * 1024)
    data = tmp_path / "Assembly"
    (data / "nested").mkdir(parents=True)
    (data / "big.dat").write_bytes(b"y" * (5 * 1024 * 1024))
    (data / "nested" / "more.dat").write_bytes(b"z" * (3 * 1024 * 1024))

    size = project_size_gb(str(proj))
    assert size > 7.5 / 1024, "must include the data directory"
    assert size < 9.0 / 1024


def test_size_of_missing_project_is_zero(tmp_path):
    assert project_size_gb(str(tmp_path / "absent.rsproj")) == 0.0


def test_rsproj_with_no_data_dir_is_just_the_file(tmp_path):
    proj = tmp_path / "Solo.rsproj"
    proj.write_bytes(b"x" * (2 * 1024 * 1024))
    assert 1.5 / 1024 < project_size_gb(str(proj)) < 2.5 / 1024


def test_guard_arithmetic_refuses_the_real_incident():
    # The measured numbers from the incident: a 119.5 GB project with 157 GB
    # free passed the old 2x-floor threshold and should fail the new one.
    project_gb, free_gb = 119.5, 157.0
    assert free_gb >= MIN_FREE_GB * 2, "old threshold let this through"
    assert project_gb + MIN_FREE_GB > free_gb, "new guard must refuse it"


def test_guard_arithmetic_allows_a_copy_that_genuinely_fits():
    project_gb, free_gb = 40.0, 300.0
    assert project_gb + MIN_FREE_GB <= free_gb
