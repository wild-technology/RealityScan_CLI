"""Single source of truth for the four physical rig cameras.

The rig carries FOUR cameras that appear under era-specific filename
families (owner-confirmed 2026-07-23):

- Zeuss      (rectilinear 23 mm full frame): 'zeuss'/'HERC' names
- Port       (fisheye 14 mm full frame):     'cammid*' or WCA 'P###C*'
- Cinema     (rectilinear 17 mm full frame): 'camlower*' or WCA 'C###C*'
- Starboard  (fisheye 14 mm full frame):     'camupper*' or WCA 'S###C*'

Calibration/lens groups are per PHYSICAL camera, never per lens type:
Port and Starboard share a lens spec but are different units with
different real intrinsics. Groups matter because the WCA JPGs are
EXIF-identical (Z CAM E2-F6, no focal tag) -- without the XMP groups
RealityScan cannot separate the cameras at all.

Mount geometry (pitch offsets, lever arms) is deliberately NOT here:
it changes per cruise; see modules/georeference/georeference_images.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# WCA rendered-still naming: P231C0003_<ts>_edt.jpg (P=Port, C=Cinema,
# S=Starboard; digits vary by cruise/sequence).
_WCA_PREFIX = re.compile(r'^([pcs])\d+c', re.IGNORECASE)


@dataclass(frozen=True)
class Camera:
    key: str                 # canonical name, also the batch subfolder
    calibration_group: str   # per physical camera
    calibration_prior: str
    focal_length_35mm: float | None
    lens_distortion_group: str
    lens_distortion_prior: str
    distortion_model: str    # per-image XMP model ('division' fisheye,
                             # 'brown3' rectilinear)


CAMERAS: dict[str, Camera] = {
    'zeuss': Camera('zeuss', '1', 'Approximate', 23.0, '1', 'Approximate', 'brown3'),
    # Port/Starboard fisheye: prior 'Approximate' throughout (owner
    # directive 2026-07-25). Verified NOT to pin distortion at zero even
    # with no coefficients supplied: cinema has always carried
    # LensDistortionPrior='Approximate' with no coefficients and still
    # solved k1 = -0.0524 across 2,204 cameras. 'Unknown' gave the solver
    # no wiggle-room hint at all.
    'port': Camera('port', '2', 'Approximate', 16.0, '2', 'Approximate', 'division'),
    # Cinema focal 17.0 -> 16.0: owner-confirmed 2026-07-25 ("C=16"),
    # corroborated by the solver's own median 16.37 mm 35-eq over 2,204
    # cameras in the fresh run.
    'cinema': Camera('cinema', '3', 'Approximate', 16.0, '3', 'Approximate', 'brown3'),
    'starboard': Camera('starboard', '4', 'Approximate', 16.0, '4', 'Approximate', 'division'),
}

# Legacy cam* filename families map onto the same physical cameras.
_LEGACY_PREFIXES = {
    'cammid': 'port',
    'camlower': 'cinema',
    'camupper': 'starboard',
}

_WCA_LETTER = {'p': 'port', 'c': 'cinema', 's': 'starboard'}


def identify(filename: str) -> Camera | None:
    """Physical camera for an image filename, or None when unknown."""
    name = filename.lower()
    if 'zeuss' in name or 'herc' in name:
        return CAMERAS['zeuss']
    for prefix, key in _LEGACY_PREFIXES.items():
        if name.startswith(prefix):
            return CAMERAS[key]
    match = _WCA_PREFIX.match(name)
    if match:
        return CAMERAS[_WCA_LETTER[match.group(1).lower()]]
    return None


def calibration_xmp(camera: Camera) -> str:
    """Calibration-ONLY XMP sidecar content for a camera.

    Deliberately carries no pose entries: exported pose sidecars
    auto-import as exact-pose priors on any later add (bug B7), and pose
    priors measurably reduced registration on NA167. Calibration groups
    are what separate the EXIF-identical WCA cameras.
    """
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<x:xmpmeta xmlns:x="adobe:ns:meta/" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">',
        '  <rdf:RDF>',
        '    <rdf:Description xmlns:Camera="http://www.capturingreality.com/ns/camera/1.0/" xmlns:xcr="http://www.capturingreality.com/ns/xcr/1.0/">',
        f'      <Camera:CalibrationGroup>{camera.calibration_group}</Camera:CalibrationGroup>',
        f'      <Camera:CalibrationPrior>{camera.calibration_prior}</Camera:CalibrationPrior>',
    ]
    if camera.focal_length_35mm is not None:
        lines.append(f'      <xcr:FocalLength35mm>{camera.focal_length_35mm}</xcr:FocalLength35mm>')
    lines.extend([
        f'      <Camera:LensDistortionGroup>{camera.lens_distortion_group}</Camera:LensDistortionGroup>',
        f'      <Camera:LensDistortionPrior>{camera.lens_distortion_prior}</Camera:LensDistortionPrior>',
        f'      <Camera:DistortionModel>{camera.distortion_model}</Camera:DistortionModel>',
        '    </rdf:Description>',
        '  </rdf:RDF>',
        '</x:xmpmeta>',
    ])
    return '\n'.join(lines)


def ensure_calibration_sidecars(image_root: str) -> tuple[int, int]:
    """Recreate a calibration-only XMP for every image that has none.

    REQUIRED after any workflow that runs the identity-harvest loop:
    the harvest MOVES pose-bearing sidecars out of the image tree into
    identity_r<K>, and the last-peeled component's sidecars are never
    re-exported, so those images are left with NO calibration prior at
    all. A later re-align of the same folder then silently runs with a
    partially-ungrouped camera set - measured on fresh zone_1, where
    796 of 4,540 images (the whole bow component plus 123 others) had
    lost their sidecars and PD-4/PD-4a re-aligned in that state
    (FINDINGS 2026-07-25).

    Returns (created, unknown_camera_skipped).
    """
    import logging
    import os

    logger = logging.getLogger(__name__)
    created = skipped = 0
    for root, _dirs, files in os.walk(image_root):
        names = set(files)
        for filename in files:
            if not filename.lower().endswith(('.jpg', '.jpeg', '.png', '.heif')):
                continue
            sidecar = os.path.splitext(filename)[0] + '.xmp'
            if sidecar in names:
                continue
            camera = identify(filename)
            if camera is None:
                skipped += 1
                continue
            with open(os.path.join(root, sidecar), 'w', encoding='utf-8') as f:
                f.write(calibration_xmp(camera))
            created += 1
    if created:
        logger.info('Restored %d missing calibration sidecar(s) under %s',
                    created, image_root)
    if skipped:
        logger.warning('%d image(s) of unknown camera type left without a '
                       'calibration sidecar', skipped)
    return created, skipped


def sanitize_and_census(image_root: str) -> tuple[int, int, int]:
    """Count pose-bearing XMP sidecars under image_root, then restore each
    to calibration-only content (or delete it for unknown cameras).

    RealityScan's XMP exports are the registration census - only
    registered cameras get pose entries - but leftover pose sidecars
    auto-import as exact-pose priors on any later add of the same images
    (bug B7), so they must never survive past the census read.

    Returns (pose_count, restored, removed).
    """
    import logging
    import os

    logger = logging.getLogger(__name__)
    pose_count = restored = removed = 0
    removed_examples: list[str] = []
    for root, _dirs, files in os.walk(image_root):
        for filename in files:
            if not filename.lower().endswith('.xmp'):
                continue
            path = os.path.join(root, filename)
            try:
                with open(path, encoding='utf-8', errors='replace') as f:
                    content = f.read()
            except OSError:
                continue
            if 'xcr:Position' not in content:
                continue  # already calibration-only
            pose_count += 1
            camera = identify(filename)
            if camera is not None:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(calibration_xmp(camera))
                restored += 1
                continue
            os.remove(path)
            # Ordinal sidecars (00000.xmp, 00001.xmp, ...) are EXPECTED:
            # exporting XMP for a component built from IMPORTED .rsalign
            # files names the sidecars ordinally instead of <stem>.xmp
            # (observed 2026-07-23). They are valid for the census count,
            # inert as priors (no image has an ordinal stem), and useless
            # afterwards - delete quietly.
            if os.path.splitext(filename)[0].isdigit():
                continue
            removed += 1
            if len(removed_examples) < 3:
                removed_examples.append(path)
    if removed:
        logger.warning('sanitize: %d pose sidecars of unrecognized cameras '
                       'deleted (e.g. %s)', removed, removed_examples)
    return pose_count, restored, removed
