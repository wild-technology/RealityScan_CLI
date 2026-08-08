"""Single source of truth for the rig cameras - loaded from cameras.json.

The registry DATA now lives in modules/cameras.json (owner per-camera /
per-rig settings, including the DATA-ONLY rig section for ON2026 Voyis).
This module parses that file at import time and rebuilds the exact
structures the pipeline has always consumed; every public signature is
unchanged. A one-release parity brace (_assert_parity below) re-asserts
the retired hardcoded tables against the JSON on every import, so a bad
edit to cameras.json is a hard ImportError naming the divergent key
instead of a silent behavior change. It is a SUBSET check: adding a new
expedition's camera/family to cameras.json is supported and does not trip
it - only changing or removing a legacy row does.

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

Mount geometry (pitch offsets, lever arms) keys off family() below, not
off the camera: the same Cinema unit sits 10 deg down under legacy
camlower names and 45 deg under WCA names. The runtime mount table is
still modules/georeference/georeference_images.py MOUNTS (superseded-by
cameras.json families[].mount, pending migration step (c+)).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

_CAMERAS_JSON = os.path.join(
    os.path.dirname(os.path.realpath(__file__)), 'cameras.json')


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


def _load_registry() -> dict:
    with open(_CAMERAS_JSON, encoding='utf-8') as f:
        return json.load(f)


_REGISTRY = _load_registry()

# Ordered MOST-SPECIFIC-FIRST straight from the JSON; the order is
# load-bearing (anchored WCA prefixes, then anchored legacy prefixes, then
# the delimiter-bounded zeuss/herc token - see family()).
_FAMILIES: tuple[dict, ...] = tuple(_REGISTRY['families'])

# Filename family -> physical camera. The family is the MOUNT identity and the
# camera is the OPTICAL identity; they are deliberately separate because the
# same physical camera has been mounted at different angles across cruises
# (legacy camlower sits 10 deg down, while the same Cinema unit under WCA names
# sits at 45 deg). Keying mount geometry off the CAMERA would silently change
# every legacy dataset by tens of degrees.
FAMILY_CAMERA: dict[str, str] = {f['family']: f['camera'] for f in _FAMILIES}

# Only cameras a family maps to become runtime Camera rows: the JSON also
# carries provenance-UNVERIFIED entries (voyis_left/voyis_right) reachable
# solely through its DATA-ONLY rigs section.
CAMERAS: dict[str, Camera] = {
    key: Camera(
        key,
        spec['calibration_group'],
        spec['calibration_prior'],
        spec['focal_length_35mm'],
        spec['lens_distortion_group'],
        spec['lens_distortion_prior'],
        spec['distortion_model'],
    )
    for key, spec in _REGISTRY['cameras'].items()
    if key in FAMILY_CAMERA.values()
}

# Compiled per-family matchers, in JSON order. IGNORECASE plus the lower()
# in family() keeps the historical case behavior for any pattern.
_MATCHERS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(f['pattern'], re.IGNORECASE), f['family']) for f in _FAMILIES
)


# ---------------------------------------------------------------------------
# Parity brace (keep for ONE release, then delete with migration step (c+)):
# the pre-JSON hardcoded tables, byte-for-byte. cameras.json must still
# CONTAIN every row below, unchanged and in the same relative order; a
# divergence aborts the import so no run can proceed on a silently-changed
# registry. ADDING cameras/families is explicitly allowed - see
# _assert_parity's docstring.

_LEGACY_CAMERAS: dict[str, Camera] = {
    'zeuss': Camera('zeuss', '1', 'Approximate', 23.0, '1', 'Approximate', 'brown3'),
    'port': Camera('port', '2', 'Approximate', 16.0, '2', 'Approximate', 'division'),
    'cinema': Camera('cinema', '3', 'Approximate', 16.0, '3', 'Approximate', 'brown3'),
    'starboard': Camera('starboard', '4', 'Approximate', 16.0, '4', 'Approximate', 'division'),
}

_LEGACY_FAMILY_CAMERA: dict[str, str] = {
    'zeuss': 'zeuss',
    'legacy_camupper': 'starboard',
    'legacy_cammid': 'port',
    'legacy_camlower': 'cinema',
    'wca_port': 'port',
    'wca_cinema': 'cinema',
    'wca_starboard': 'starboard',
}

# family -> regex source, in match order. The three per-letter WCA rows are
# the old single `^([pcs])\d+c` prefix split per family; the legacy rows are
# the old startswith() prefixes, anchored; zeuss is the old token unchanged.
_LEGACY_FAMILY_PATTERNS: tuple[tuple[str, str], ...] = (
    ('wca_port', r'^p\d+c'),
    ('wca_cinema', r'^c\d+c'),
    ('wca_starboard', r'^s\d+c'),
    ('legacy_camupper', r'^camupper'),
    ('legacy_cammid', r'^cammid'),
    ('legacy_camlower', r'^camlower'),
    ('zeuss', r'(^|[_\-.])(zeuss|herc)([_\-.]|$)'),
)


def _assert_parity() -> None:
    """Every retired legacy row must still be PRESENT and UNCHANGED in
    cameras.json, and the legacy patterns must keep their relative order.

    ADDITIONS ARE ALLOWED. This used to demand a byte-for-byte
    reproduction - exact family set, exact family COUNT - which made
    "add your expedition's camera to cameras.json" a hard ImportError that
    bricked main.py, wildscan and every standalone driver at once, even
    though the module's own docstring calls that file the place owner
    per-rig settings live (audit 2026-08-07). The brace's real job is to
    prove no legacy behaviour drifted while the JSON became the source of
    truth, and a subset check proves exactly that.

    Order still matters for the legacy rows because family() walks the
    list MOST SPECIFIC FIRST (an unanchored 'herc' token once beat an
    anchored WCA prefix). New rows may sit anywhere; if a new pattern
    shadows a legacy one, THAT is the author's problem to test - the
    relative order of the seven legacy rows is what is pinned here.
    """
    for key, legacy in sorted(_LEGACY_CAMERAS.items()):
        if key not in CAMERAS:
            raise ImportError(
                f'cameras.json parity: cameras[{key!r}] is MISSING - the '
                'retired legacy cameras may be extended but never removed')
        if CAMERAS[key] != legacy:
            raise ImportError(
                f'cameras.json parity: cameras[{key!r}] diverges from the '
                f'legacy table: {CAMERAS[key]!r} != {legacy!r}')
    for key, legacy in sorted(_LEGACY_FAMILY_CAMERA.items()):
        if FAMILY_CAMERA.get(key) != legacy:
            raise ImportError(
                f'cameras.json parity: families[{key!r}].camera diverges '
                f'from the legacy table: {FAMILY_CAMERA.get(key)!r} != '
                f'{legacy!r}')
    got = {f['family']: f['pattern'] for f in _FAMILIES}
    for fam, pattern in _LEGACY_FAMILY_PATTERNS:
        if got.get(fam) != pattern:
            raise ImportError(
                f'cameras.json parity: families[{fam!r}] pattern diverges: '
                f'{got.get(fam)!r} != {pattern!r}')
    order = [f['family'] for f in _FAMILIES]
    legacy_order = [fam for fam, _ in _LEGACY_FAMILY_PATTERNS]
    seen_order = [fam for fam in order if fam in set(legacy_order)]
    if seen_order != legacy_order:
        raise ImportError(
            f'cameras.json parity: the legacy families changed relative '
            f'order ({seen_order} != {legacy_order}); family() matching is '
            'most-specific-first and the order is load-bearing')


_assert_parity()


def family(filename: str) -> str | None:
    """Mount family for an image filename, or None when unknown.

    Matching walks the JSON family list MOST SPECIFIC FIRST: anchored WCA
    prefix, then anchored legacy prefix, then a delimiter-bounded
    zeuss/herc token. The order is pinned by _assert_parity - an unanchored
    `'herc' in name` test once ran FIRST and would have won against an
    anchored WCA prefix.

    Callers needing per-cruise mount geometry must key off THIS, never off
    cruise digits. The literal 'p231c'/'c231c' tests that used to live in the
    georeferencer meant the next cruise's 'C245C0007_*.jpg' fell through to a
    zero lever arm and 0 deg pitch offset - a wrong prior asserted at 10 deg
    confidence, with one suppressed warning for the whole run.
    """
    name = filename.lower()
    for pattern, fam in _MATCHERS:
        if pattern.search(name):
            return fam
    return None


def identify(filename: str) -> Camera | None:
    """Physical camera for an image filename, or None when unknown."""
    fam = family(filename)
    return None if fam is None else CAMERAS[FAMILY_CAMERA[fam]]


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
