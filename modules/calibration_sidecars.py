"""Per-eye APPROXIMATE calibration XMPs for stereo-rig campaigns
(owner directive 2026-08-08: when using COLMAP output, calibration groups
are set PER-CAMERA and the manufacturer resized-corrected calibration is
supplied as an Approximate prior).

DELIVERY (owner finding 2026-08-08): same-name sidecar auto-import is
UNRELIABLE - do not write these next to images and trust the pairing.
Write them into a separate directory and feed each file explicitly with
`-addImageWithCalibration <imagePath> <xmpPath>` (RS 2.2 allcommands),
the hard-coded-paths pattern the flight-log workflow uses. Grouping
alone needs no files: -selectImage + -setPriorCalibrationGroup/
-setPriorLensGroup. See FINDINGS.md 2026-08-08.

Writes calibration-ONLY XMPs (no pose entries - pose priors come from the
flight log; exported pose sidecars auto-import as exact priors, bug B7)
in the xcr/1.1 attribute form RealityScan emits itself, with per-eye
CalibrationGroup/DistortionGroup so left and right calibrate
independently.

The pixel intrinsics convention (verified against RealityScan's own
exported sidecars on ON2026 zone_12):
  FocalLength35mm  = fx / width * 36
  PrincipalPointU  = (cx - width / 2) / width
  PrincipalPointV  = (cy - height / 2) / height
"""
from __future__ import annotations

import os

XMP_TEMPLATE = (
    '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
    '  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
    '    <rdf:Description xcr:Version="4"\n'
    '       xcr:CalibrationPrior="{prior}" xcr:CalibrationGroup="{group}"\n'
    '       xcr:DistortionGroup="{group}" xcr:DistortionModel="{distortion}"\n'
    '       xcr:DistortionCoeficients="0 0 0 0 0 0"\n'
    '       xcr:FocalLength35mm="{focal35}" xcr:Skew="0"\n'
    '       xcr:AspectRatio="1" xcr:PrincipalPointU="{ppu}"\n'
    '       xcr:PrincipalPointV="{ppv}"\n'
    '       xmlns:xcr="http://www.capturingreality.com/ns/xcr/1.1#">\n'
    '    </rdf:Description>\n'
    '  </rdf:RDF>\n'
    '</x:xmpmeta>\n')


def intrinsics_to_xmp_values(intrinsics, resolution) -> dict:
    """RS-normalized calibration from a 3x3 pixel intrinsics matrix."""
    fx = float(intrinsics[0][0])
    cx = float(intrinsics[0][2])
    cy = float(intrinsics[1][2])
    w, h = float(resolution[0]), float(resolution[1])
    return {
        "focal35": fx / w * 36.0,
        "ppu": (cx - w / 2.0) / w,
        "ppv": (cy - h / 2.0) / h,
    }


def eye_of(basename: str) -> str | None:
    """'L'/'R' from a staged (L_/R_) or original (image_left_/image_right_)
    VOYIS filename; None when the name carries no eye token."""
    b = basename.lower()
    if b.startswith("l_") or "image_left_" in b or "_left_" in b:
        return "L"
    if b.startswith("r_") or "image_right_" in b or "_right_" in b:
        return "R"
    return None


def write_sidecars(image_dir: str, intrinsics, resolution,
                   prior: str = "approximate",
                   distortion: str = "division") -> dict:
    """Write per-image calibration XMPs under image_dir (recursive), one
    calibration/distortion GROUP per eye (L=0, R=1). Returns counts.
    NEVER point this at a production zone in place - sidecars auto-import
    on the next add; write into a copy."""
    vals = intrinsics_to_xmp_values(intrinsics, resolution)
    counts = {"L": 0, "R": 0, "skipped_no_eye": 0}
    for root, _dirs, files in os.walk(image_dir):
        for fn in files:
            if not fn.lower().endswith((".jpg", ".jpeg", ".png")):
                continue
            eye = eye_of(fn)
            if eye is None:
                counts["skipped_no_eye"] += 1
                continue
            xmp = XMP_TEMPLATE.format(
                prior=prior, group=0 if eye == "L" else 1,
                distortion=distortion, focal35=f"{vals['focal35']:.10f}",
                ppu=f"{vals['ppu']:.10f}", ppv=f"{vals['ppv']:.10f}")
            out = os.path.join(root, os.path.splitext(fn)[0] + ".xmp")
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(xmp)
            counts[eye] += 1
    return counts
