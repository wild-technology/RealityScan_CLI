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
EXIF-identical (Z CAM E2-F6, no focal tag) -- without an explicit group
RealityScan cannot separate the cameras at all.

Those groups are now applied IN-SESSION through the RealityScan CLI
(`-selectImage` + `-setPriorCalibrationGroup` / `-setPriorLensGroup`, see
modules/prior_groups.py), NOT by writing XMP sidecars beside the images.
The sidecar path is retired: it was never the only mechanism, and owning
every image-adjacent .xmp is what let the identity harvest strip 17.5% of
zone_1's calibration priors and sweep ON2026's hand-placed files.

RECON 2026-09-03: on the reconciled tree the paragraph above is the
remove-xmp-sidecars position, not a settled fact. main's align path still
writes and harvests XMP by DEFAULT (ensure_calibration_sidecars below runs
on every exit path of __align_zone unless RS_LEGACY_XMP_IDENTITY=0), and
the in-session prior-group file (modules/prior_groups.py,
RS_PRIOR_GROUPS_FILE) is applied alongside it. Which of the two RealityScan
honours from the delegated CLI is open decision D1 - FINDINGS.md
`[RECON] 2026-09-03`.

RECON 2026-09-11: v02 import/readback refutes the claim that calibration
sidecars are unnecessary: CSV focal stayed zero; legacy Camera elements
left groups unset and scaled focal 36x. Native xcr calibration attributes
delivered focal/model/groups. Both explicit group setters worked, but
ifKGrp=1 subsequently collapsed their groups. Fresh alignment now uses
native calibration-only XMP plus one CSV pose/accuracy import with grouping
0 and a measured input census. This does NOT flip RS_LEGACY_XMP_IDENTITY
or change the separate solved-pose/continuation/merge-export ownership lane.

Mount geometry (pitch offsets, lever arms) keys off family() below, not
off the camera: the same Cinema unit sits 10 deg down under legacy
camlower names and 45 deg under WCA names. The runtime mount table is
still modules/georeference/georeference_images.py MOUNTS (superseded-by
cameras.json families[].mount, pending migration step (c+)).
"""
from __future__ import annotations

import json
import copy
import hashlib
import math
import os
import re
import xml.etree.ElementTree as ET
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
    # Optional full-intrinsics prior (manufacturer-verified rigs, e.g.
    # VOYIS): normalized principal-point offsets. When present,
    # calibration_xmp emits the RS-native attribute form incl. PPU/PPV.
    principal_point_u: float | None = None
    principal_point_v: float | None = None
    # When set, ensure_calibration_sidecars CREATES sidecars for this
    # camera only if the named env var is truthy - registering a family
    # must never flip production behavior by side effect; the
    # calibration-prior A/B decides adoption (2026-08-08).
    opt_in_env: str | None = None


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
        principal_point_u=spec.get('principal_point_u'),
        principal_point_v=spec.get('principal_point_v'),
        opt_in_env=spec.get('opt_in_env'),
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

# 2026-09-08, OWNER DIRECTIVE: "NOTHING SHOULD EVER BE BROWN3, only DIVISION."
# zeuss and cinema carried 'brown3' here and the brace pinned it, so the rows
# below were amended DELIBERATELY rather than the brace being loosened.
#
# This is not cosmetic. RS_CLI/Metadata/AlignmentParams.xml sets a GLOBAL
# sfmDistortionModel=Division, so every sidecar written for a brown3 camera
# declared a model the session was not configured for. Measured on NA165/H2060
# zone_1 (3,000 harvested cameras, 2026-09-08): every exported camera carried
# BOTH Camera:DistortionModel="brown3" (our prior) and
# xcr:DistortionModel="division" (what actually solved) - i.e. the prior lost.
# A calibration prior that contradicts the session distortion model is a strong
# candidate for why RealityScan discarded the sidecar wholesale; see the
# CalibrationGroup="-1" census in FINDINGS (B17).
_LEGACY_CAMERAS: dict[str, Camera] = {
    'zeuss': Camera('zeuss', '1', 'Approximate', 23.0, '1', 'Approximate', 'division'),
    'port': Camera('port', '2', 'Approximate', 16.0, '2', 'Approximate', 'division'),
    'cinema': Camera('cinema', '3', 'Approximate', 16.0, '3', 'Approximate', 'division'),
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


def families_in_match_order() -> tuple[dict, ...]:
    """The family specs in the SAME most-specific-first order family() walks.

    Exposed for modules/prior_groups.py, which must emit its per-family
    `-selectImage` / `-setPrior*Group` commands in this order: the patterns
    deliberately overlap (an unanchored zeuss/herc token would otherwise
    beat an anchored WCA prefix), so a later selection must be allowed to
    re-group images an earlier, broader one already touched.
    """
    return copy.deepcopy(_FAMILIES)


def load_project_priors(path: str | None) -> dict:
    """Validate a data-only project contract without changing process state.

    Schema 1: required schema_version=1, orientation_weight=2; optional
    families={family: {fwd,lat,down,pitch,p_acc}}, defaults={position_accuracy_m:
    {x,y,alt}, orientation_accuracy_deg:{yaw,roll}}, navigation={
    clock_offset_seconds,max_match_seconds}. All dictionaries are partial,
    except a previously unmeasured mount requires all five fields. Unknown
    keys, duplicate JSON keys, booleans and nonfinite numbers are errors.

    Metres: lever arms [-1000,1000], accuracy (0,1e6]; degrees: down-tilt
    [-180,180] except Zeuss [0,90] (owner: never up, at most nadir),
    accuracy (0,180]; clock seconds [-86400,86400], matching
    tolerance [0,3600]. These are input-validation limits, not science priors.
    """
    empty = dict(source=None, sha256=None, families={}, defaults={}, navigation={},
                 schema_version=1, orientation_weight=2.0)
    if path is None:
        return empty
    if not isinstance(path, str) or not path.strip() or not os.path.isabs(path):
        raise ValueError('RS_CAMERA_PRIORS_FILE must be an absolute JSON file path')

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate project-prior JSON key: {key}')
            result[key] = value
        return result

    def fields(value, allowed, label):
        if not isinstance(value, dict) or set(value) - set(allowed):
            raise ValueError(f'Unknown fields or invalid object in project priors: {label}')
        return value

    def number(value, lower, upper, label, positive=False):
        if (type(value) not in (int, float) or not lower <= value <= upper
                or not math.isfinite(value) or (positive and value <= 0)):
            raise ValueError(f'Invalid project-prior numeric value for {label}: {value!r}')
        return float(value)

    def reject_constant(value):
        raise ValueError(f'Nonfinite project-prior JSON value: {value}')

    try:
        with open(path, 'rb') as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError('Project-prior JSON exceeds 1 MiB')
        data = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique_object,
                          parse_constant=reject_constant)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f'Cannot load project priors {path!r}: {exc}') from exc
    fields(data, ('schema_version', 'orientation_weight', 'families', 'defaults', 'navigation'), 'root')
    if type(data.get('schema_version')) is not int or data['schema_version'] != 1:
        raise ValueError('Project priors require schema_version=1')
    weight = number(data.get('orientation_weight'), 2, 2, 'orientation_weight')
    mounts = fields(data.get('families', {}), FAMILY_CAMERA, 'families')
    allowed_mount = {'fwd', 'lat', 'down', 'pitch', 'p_acc'}
    base_mounts = {entry['family']: entry['mount'] for entry in _FAMILIES}
    excluded = _REGISTRY['defaults']['assumed_mount']['excluded_families']
    for name, values in mounts.items():
        fields(values, allowed_mount, name)
        if name in excluded:
            raise ValueError(f'Project vehicle-mount priors are not applicable to {name}')
        if base_mounts[name] is None and set(values) != allowed_mount:
            raise ValueError(f'Unmeasured family {name} requires all five mount fields')
        for key, value in values.items():
            if key == 'pitch':
                limits = (0, 90) if name == 'zeuss' else (-180, 180)
            elif key == 'p_acc':
                # Uncertainty is not a mechanical stop or a truncated interval.
                limits = (0, 180)
            else:
                limits = (-1000, 1000)
            values[key] = number(value, *limits, f'{name}.{key}', positive=key == 'p_acc')
    defaults = fields(data.get('defaults', {}),
                      ('position_accuracy_m', 'orientation_accuracy_deg'), 'defaults')
    for name, values in defaults.items():
        position = name == 'position_accuracy_m'
        fields(values, ('x', 'y', 'alt') if position else ('yaw', 'roll'), name)
        for key, value in values.items():
            values[key] = number(value, 0, 1e6 if position else 180,
                                 f'{name}.{key}', positive=True)
    navigation = fields(data.get('navigation', {}),
                        ('clock_offset_seconds', 'max_match_seconds'), 'navigation')
    for key, value in navigation.items():
        limits = (-86400, 86400) if key == 'clock_offset_seconds' else (0, 3600)
        navigation[key] = number(value, *limits, key)
    return dict(source=os.path.abspath(path), sha256=hashlib.sha256(raw).hexdigest(),
                schema_version=1, orientation_weight=weight, families=mounts,
                defaults=defaults, navigation=navigation)


# Snapshot once, before consumers cache mount/default tables. Changing the GUI
# environment later cannot silently retune an already-started worker process.
_PROJECT_PRIORS = load_project_priors(os.environ.get('RS_CAMERA_PRIORS_FILE'))


def project_priors_active() -> bool:
    return _PROJECT_PRIORS['source'] is not None


def baked_mount_defaults() -> dict[str, dict | None]:
    """New-project mount defaults; ignore any active project-prior snapshot."""
    return {entry['family']: (None if entry['mount'] is None else
            {key: value for key, value in entry['mount'].items() if not key.startswith('_')})
            for entry in _FAMILIES}


def baked_prior_defaults() -> dict:
    """New-project accuracy defaults, copied from the baked registry only."""
    return copy.deepcopy(_REGISTRY['defaults'])


def mount_defaults() -> dict[str, dict | None]:
    """Effective project mounts, with defensive per-field registry fallback."""
    mounts = baked_mount_defaults()
    for name, values in _PROJECT_PRIORS['families'].items():
        mounts[name] = {**(mounts[name] or {}), **values}
    return mounts


def prior_defaults() -> dict:
    """Effective project accuracy defaults, with defensive registry fallback."""
    defaults = baked_prior_defaults()
    for name, values in _PROJECT_PRIORS['defaults'].items():
        defaults[name].update(values)
    return defaults


def navigation_defaults() -> dict:
    return {'clock_offset_seconds': 0.0, 'max_match_seconds': 2.0,
            **_PROJECT_PRIORS['navigation']}


def effective_project_priors() -> dict:
    """Serializable startup provenance for the controller's project metadata."""
    return dict(source=_PROJECT_PRIORS['source'], sha256=_PROJECT_PRIORS['sha256'],
                schema_version=1, orientation_weight=2.0, families=mount_defaults(),
                defaults=prior_defaults(), navigation=navigation_defaults())


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
    if camera.principal_point_u is not None:
        return _calibration_xmp_full_intrinsics(camera)
    # v02 import/readback 2026-09-11: legacy Camera elements left groups
    # unassigned and scaled focal 36x. Native xcr attributes deliver both.
    # Keep the public API and the separate full-intrinsics/continuation lanes.
    if camera.calibration_prior.lower() not in ('approximate', 'initial'):
        raise ValueError(f'Unverified native calibration prior: {camera.calibration_prior}')
    focal = camera.focal_length_35mm
    if focal is None or not math.isfinite(focal) or focal <= 0:
        raise ValueError(f'Calibration focal must be finite and positive: {camera.key}')
    xcr = 'http://www.capturingreality.com/ns/xcr/1.1#'
    rdf = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'
    ET.register_namespace('x', 'adobe:ns:meta/')
    ET.register_namespace('rdf', rdf)
    ET.register_namespace('xcr', xcr)
    root = ET.Element('{adobe:ns:meta/}xmpmeta')
    body = ET.SubElement(root, f'{{{rdf}}}RDF')
    attributes = dict(Version='3', CalibrationPrior='initial',
                      CalibrationGroup=str(camera.calibration_group),
                      DistortionGroup=str(camera.lens_distortion_group),
                      DistortionModel=camera.distortion_model,
                      FocalLength35mm=format(focal, '.15g'))
    for name in ('CalibrationGroup', 'DistortionGroup'):
        if not re.fullmatch(r'\d+', attributes[name]) or int(attributes[name]) >= 4294967295:
            raise ValueError(f'Invalid assigned {name}: {attributes[name]}')
    ET.SubElement(body, f'{{{rdf}}}Description', {f'{{{xcr}}}{key}': value for key, value in attributes.items()})
    return ET.tostring(root, encoding='unicode')


def validate_calibration_xmp(content: str, camera: Camera) -> None:
    """Read-only exact native calibration check for NEW alignment inputs.

    This must not be applied to solved/continuation/export XMPs, which may
    legitimately contain poses and adjusted intrinsics. It never rewrites them.
    """
    if re.search(r'<!\s*(DOCTYPE|ENTITY)\b', content, re.IGNORECASE):
        raise ValueError('DTD/entities are not calibration input evidence')
    actual = ET.fromstring(content)
    expected = ET.fromstring(calibration_xmp(camera))
    numeric = {'FocalLength35mm', 'PrincipalPointU', 'PrincipalPointV', 'Skew', 'AspectRatio'}

    def shape(node):
        attributes = {}
        for key, value in node.attrib.items():
            if key.rsplit('}', 1)[-1] in numeric:
                value = float(value)
                if not math.isfinite(value):
                    raise ValueError('Nonfinite calibration value')
            attributes[key] = value
        return node.tag, attributes, (node.text or '').strip(), [shape(child) for child in node]

    if shape(actual) != shape(expected):
        raise ValueError(f'Calibration sidecar differs from native profile for {camera.key}; '
                         'legacy, stale or pose-bearing inputs require separate owned staging')


def _calibration_xmp_full_intrinsics(camera: Camera) -> str:
    """RS-native attribute-form calibration sidecar for cameras carrying a
    full manufacturer-verified intrinsics prior (principal point present).
    Mirrors the form RealityScan itself exports (verified on ON2026
    zone_12 sidecars); no pose entries (B7)."""
    return (
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
        '  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        '    <rdf:Description xcr:Version="4"\n'
        f'       xcr:CalibrationPrior="{camera.calibration_prior}"'
        f' xcr:CalibrationGroup="{camera.calibration_group}"\n'
        f'       xcr:DistortionGroup="{camera.lens_distortion_group}"'
        f' xcr:DistortionModel="{camera.distortion_model}"\n'
        '       xcr:DistortionCoeficients="0 0 0 0 0 0"\n'
        f'       xcr:FocalLength35mm="{camera.focal_length_35mm:.10f}"'
        ' xcr:Skew="0"\n'
        f'       xcr:AspectRatio="1"'
        f' xcr:PrincipalPointU="{camera.principal_point_u:.10f}"\n'
        f'       xcr:PrincipalPointV="{camera.principal_point_v:.10f}"\n'
        '       xmlns:xcr="http://www.capturingreality.com/ns/xcr/1.1#">\n'
        '    </rdf:Description>\n'
        '  </rdf:RDF>\n'
        '</x:xmpmeta>\n')


def ensure_calibration_sidecars(image_root: str) -> tuple[int, int]:
    """Recreate a calibration-only XMP for every image that has none.

    SCOPE (2026-08-08): this same-name auto-import pathway is the WCA
    (H2023) production mechanism and stays for that pipeline. For the
    COLMAP-bridge stereo path (VOYIS) the owner found sidecar
    auto-import unreliable in the field - those families are env-gated
    below, and calibration priors travel via explicit CLI commands
    instead (-addImageWithCalibration / -setPriorCalibrationGroup;
    FINDINGS.md 2026-08-08).

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
            from .image_exts import is_geometry_image, PROCESSABLE_IMAGE_EXTS
            if not is_geometry_image(os.path.join(root, filename), PROCESSABLE_IMAGE_EXTS):
                continue
            sidecar = os.path.splitext(filename)[0] + '.xmp'
            if sidecar in names:
                continue
            camera = identify(filename)
            if camera is None:
                skipped += 1
                continue
            if camera.opt_in_env and not os.environ.get(camera.opt_in_env):
                # Registered family, gated creation: adoption of
                # calibration priors is an A/B decision, never a side
                # effect of registering the family (2026-08-08).
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


def assert_sidecars_current(image_root: str, logger=None, strict: bool = True) -> dict:
    """Refuse to align against sidecars that do not match the images present.

    A STALE sidecar set is silent and dangerous, and it recurs. The failure
    modes this catches, all seen in practice:

    - POSE-BEARING sidecars beside images. RealityScan auto-imports those as
      EXACT-POSE priors on any later add (bug B7), so a re-align inherits the
      previous solve's poses and cannot disagree with it.
    - ORPHANED sidecars - a `.xmp` whose image is gone. That means the tree
      was rebuilt from a different image set and the sidecars were not, so
      they describe images that are not here. On 2026-08-14 an H2082 batch
      carried 7,694 sidecars for a set that had become 4,903 images after
      thumbnail contamination was removed.
    - WRONG-GROUP sidecars - the calibration group does not match what the
      filename's family resolves to, i.e. the registry changed (or the file
      was written for another cruise) and the sidecars were not regenerated.

    Returns a dict of counts. Raises RuntimeError when strict and anything
    is wrong, because every one of these silently corrupts a solve rather
    than failing it.
    """
    import logging
    import os

    log = logger or logging.getLogger(__name__)
    exts = ('.jpg', '.jpeg', '.png', '.heif')
    pose: list[str] = []
    orphaned: list[str] = []
    wrong_group: list[str] = []
    uncovered = 0
    sidecars = 0

    for root, _dirs, files in os.walk(image_root):
        # identity_r<K>/ folders are the harvest's OWN output - pose sidecars
        # live there by design and are not beside any image.
        if os.path.basename(root).startswith('identity_'):
            continue
        names = {f.lower() for f in files}
        for filename in files:
            if not filename.lower().endswith('.xmp'):
                continue
            sidecars += 1
            path = os.path.join(root, filename)
            stem = os.path.splitext(filename)[0]
            if not any((stem + e).lower() in names for e in exts):
                orphaned.append(path)
                continue
            try:
                content = open(path, encoding='utf-8', errors='replace').read()
            except OSError:
                continue
            if 'xcr:Position' in content:
                pose.append(path)
            camera = identify(filename)
            if camera is not None:
                g = camera.calibration_group
                # Both sidecar shapes this registry writes: the element form
                # from calibration_xmp() and the attribute form from
                # _calibration_xmp_full_intrinsics() (principal-point cameras,
                # i.e. the env-gated VOYIS eyes). Reconciled 2026-09-03.
                if (f'<Camera:CalibrationGroup>{g}<' not in content
                        and f'xcr:CalibrationGroup="{g}"' not in content):
                    wrong_group.append(path)
        for filename in files:
            from .image_exts import is_geometry_image
            if not is_geometry_image(os.path.join(root, filename), exts):
                continue
            if identify(filename) is None:
                continue
            if (os.path.splitext(filename)[0] + '.xmp').lower() not in names:
                uncovered += 1

    result = {
        'sidecars': sidecars,
        'pose_bearing': len(pose),
        'orphaned': len(orphaned),
        'wrong_group': len(wrong_group),
        'images_without_sidecar': uncovered,
    }

    # Pose-bearing sidecars are WARNED, not refused. The align path already
    # announces them ("HEADS UP: ... contains N pose-bearing .xmp") because
    # the identity harvest moves them out and never returns them, and that
    # announcement is a documented contract with a test behind it
    # (testing/test_align_and_rollback_safety.py). Raising here would take
    # that warning away and turn a handled case into a hard stop.
    if pose:
        log.warning('%d pose-bearing sidecar(s) beside images under %s - they '
                    'auto-import as EXACT-POSE priors (bug B7) and the harvest '
                    'will move them out without returning them.',
                    len(pose), image_root)

    problems = []
    if orphaned:
        problems.append(f'{len(orphaned)} ORPHANED sidecar(s) with no matching '
                        f'image - the tree was rebuilt but the sidecars were '
                        f'not, e.g. {os.path.basename(orphaned[0])}')
    if wrong_group:
        problems.append(f'{len(wrong_group)} sidecar(s) whose calibration group '
                        f'contradicts the registry, e.g. '
                        f'{os.path.basename(wrong_group[0])}')

    if problems:
        message = (f'Sidecars under {image_root} are NOT current: '
                   + '; '.join(problems)
                   + '. Regenerate them (ensure_calibration_sidecars) or delete '
                     'them before aligning - a stale sidecar corrupts a solve '
                     'silently rather than failing it.')
        if strict:
            raise RuntimeError(message)
        log.error(message)
    else:
        log.info('Sidecar check OK under %s: %d sidecar(s), %d image(s) '
                 'without one', image_root, sidecars, uncovered)
    return result


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
