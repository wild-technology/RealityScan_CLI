"""Per-eye approximate calibration sidecars (owner directive 2026-08-08).
The convention under test was verified against RealityScan's own exported
sidecars on ON2026 zone_12."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.calibration_sidecars import (
    eye_of, intrinsics_to_xmp_values, write_sidecars)

VOYIS_K = [[1895.6747569500258, 0, 1444.9779663085938],
           [0, 1895.6747569500258, 1386.6773681640625], [0, 0, 1]]
RES = [2816, 2816]


def test_intrinsics_conversion_matches_rs_convention():
    v = intrinsics_to_xmp_values(VOYIS_K, RES)
    # cross-checked against RS's own zone_12 export (24.211/0.01267/-0.00679
    # were RS's SOLVED values; these are the manufacturer priors)
    assert abs(v["focal35"] - 24.234478) < 1e-5
    assert abs(v["ppu"] - 0.01313138) < 1e-7
    assert abs(v["ppv"] - (-0.00757196)) < 1e-7


def test_eye_detection_staged_and_original_names():
    assert eye_of("L_2026-06-21_x_000001.jpg") == "L"
    assert eye_of("R_2026-06-21_x_000001.jpg") == "R"
    assert eye_of("20250527T162458_image_left_processed_D.jpg") == "L"
    assert eye_of("20250527T162458_image_right_processed_D.jpg") == "R"
    assert eye_of("2026-06-21_13-20-20.752926_000001.jpg") is None


def test_write_sidecars_per_eye_groups(tmp_path):
    d = tmp_path / "rig"
    d.mkdir()
    (d / "L_a.jpg").write_bytes(b"j")
    (d / "R_a.jpg").write_bytes(b"j")
    (d / "noeye.jpg").write_bytes(b"j")
    counts = write_sidecars(str(d), VOYIS_K, RES)
    assert counts == {"L": 1, "R": 1, "skipped_no_eye": 1}
    left = (d / "L_a.xmp").read_text(encoding="utf-8")
    right = (d / "R_a.xmp").read_text(encoding="utf-8")
    assert 'xcr:CalibrationGroup="0"' in left
    assert 'xcr:CalibrationGroup="1"' in right
    assert 'xcr:CalibrationPrior="approximate"' in left
    assert 'xcr:DistortionModel="division"' in left
    assert 'xcr:FocalLength35mm="24.2344784269"' in left
    assert "Position" not in left and "Rotation" not in left  # no pose (B7)
    assert not (d / "noeye.xmp").exists()
