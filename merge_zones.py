#!/usr/bin/env python3
"""Feature-aware cross-zone merge driver (reworked 2026-07-24).

Replaces the maximal-fraction ladder with the workflow the bow/hull
governing intent requires (HANDOFF workflow-evaluation queue;
docs/history/MERGE_REWORK_RECOMMENDATIONS.md):

1. Manifests -> twin resolution -> border graph -> CONNECTED CLUSTERS.
   Components whose UTM bboxes never touch are different physical
   features; no merge mechanism can or should fuse them. Each cluster
   gets its own merge scene; single-component clusters get ZERO attempts.
2. Per multi-component cluster: escalation ladder, one change per
   attempt, judged by census + component peel (NEVER exit status).
   Acceptance = BOUNDED LOSS: a fusion is adopted when its cameras are
   attributable to an input subset and it dropped no more than
   --loss_tolerance of the input cameras (default 0 = exact only). The
   former never-shrink rule could not accept ANY solver-lossy fusion,
   which is exactly what the rematch/high-overlap rungs produce - H2024's
   hull fused 4,860 of 4,865 cameras on every rung and was rejected all
   three times (FINDINGS 2026-07-28).
   A rung that fuses restarts the ladder on the new state; convergence
   = a full ladder cycle with no fusion. There is NO fraction target -
   two saturated disjoint features are SUCCESS. --target is
   informational only.
3. Registration CSVs measure each peeled component's image membership.
   Count arithmetic proposes parent subsets; only measured membership can
   certify retention or populate a new manifest. Count-only results remain
   diagnostic and cannot be adopted. Attempts run in fresh directories.
4. Terminal state: ONE assembly project holding EVERY surviving
   component (fused or single) at its own maximum, georeferenced via
   union flight log + -update, saved + dated copy - then an
   EVALUATION READY report for the owner gate. Optional --auto_model
   runs GenerateModel per surviving component >= min size instead of
   stopping at the gate (DEPRECATED 2026-08-07 - prefer run_models.py,
   which adds smallest-first ordering, resumability and the
   quantile-ratio scale fallback; behaviour kept for compatibility).

Usage:
    python merge_zones.py --components_root <aligned_components>
                          --images_root <batched_images_by_zone>
                          --output <merge_output_dir> [--name Merged]
                          [--min_size 50] [--project_label NA156_H2023]
                          [--visible true] [--auto_model false]
                          [--complist <file>]  (explicit component inputs)

All prompts default to the previous run's answers (rs_settings.json) -
except under a charter / RS_NO_SETTINGS_INHERITANCE, where a missing
argument is refused by name instead of inherited (module_base.settings_store).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
import time
import logging
import tempfile
import math
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from module_base.settings_store import SettingsStore, realityscan_env
from modules import camera_registry
from modules import component_analysis
from modules import component_manifest
from modules import scale_oracle
from modules import align_fingerprint
from modules.flight_logs import (assert_one_zone,
                                 epsg_for_utm_zone,
                                 utm_zone_from_flight_log_name,
                                 write_flight_log_params)
from modules.harvest_guard import assert_harvestable
from modules.realityscan_interface.realityscan_cli import (
    RealityScanCLI, METADATA_DIR, set_project_save_env)

COMPONENT_EXTENSIONS = ('.rsalign', '.rcalign')
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.heif')

ORPHAN_SELECTOR_VERSION = 'pair-local-surfaces-1'
ORPHAN_POLICY_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['horizontal_margin_m', 'vertical_margin_m', 'footprint_link_m',
                 'max_corridor_m', 'max_offered', 'vertical_datum', 'component_features'],
    'properties': {
        'horizontal_margin_m': {'type': 'number', 'minimum': 0,
                                'description': 'XY navigation uncertainty around pair support, metres'},
        'vertical_margin_m': {'type': 'number', 'minimum': 0,
                              'description': 'Uncertainty around interpolated navigation height, metres'},
        'footprint_link_m': {'type': 'number', 'exclusiveMinimum': 0,
                             'description': 'Maximum 3D edge connecting measured camera centres, metres'},
        'max_corridor_m': {'type': 'number', 'minimum': 0,
                           'description': 'Maximum 3D closest-footprint corridor length, metres'},
        'max_offered': {'type': 'integer', 'minimum': 1,
                        'description': 'Hard offered-image cap; overflow refuses the attempt'},
        'vertical_datum': {'type': 'string', 'minLength': 1, 'pattern': r'\S',
                           'description': 'Declared datum of selected flight-log height in metres'},
        'component_features': {'type': 'integer', 'enum': [0, 1, 2],
                                'description': 'Imported component feature mode; orphans independently use 2'},
        'cli_probe_evidence': {'type': 'string', 'minLength': 1,
                               'description': 'Optional absolute path to project-owned passed probe evidence'},
    },
}


def _orphan_id(name):
    return str(name).replace('\\', '/').rsplit('/', 1)[-1].casefold()


def validate_orphan_policy(policy):
    """All spatial tolerances are explicit, in metres; no campaign defaults."""
    allowed = set(ORPHAN_POLICY_SCHEMA['properties'])
    if not isinstance(policy, dict) or set(policy) - allowed:
        raise ValueError('orphan policy must be an object with only the documented policy fields')
    for key in ('horizontal_margin_m', 'vertical_margin_m', 'footprint_link_m',
                'max_corridor_m'):
        value = policy.get(key)
        if (type(value) not in (int, float) or not math.isfinite(value)
                or value < 0 or (key == 'footprint_link_m' and value == 0)):
            raise ValueError(f'orphan policy requires finite nonnegative {key}')
    if type(policy.get('max_offered')) is not int or policy['max_offered'] < 1:
        raise ValueError('orphan policy requires a positive max_offered')
    if type(policy.get('component_features')) is not int or policy['component_features'] not in (0, 1, 2):
        raise ValueError('orphan policy requires component_features 0, 1 or 2')
    if not isinstance(policy.get('vertical_datum'), str) or not policy['vertical_datum'].strip():
        raise ValueError('orphan policy requires an explicit vertical_datum')
    if 'cli_probe_evidence' in policy and (not isinstance(policy['cli_probe_evidence'], str)
            or not policy['cli_probe_evidence'].strip() or not Path(policy['cli_probe_evidence']).is_absolute()):
        raise ValueError('cli_probe_evidence must be an absolute path or omitted')


def read_orphan_policy(path, *, expected_sha256=None):
    """Shared planner/runtime validation of the exact approved policy bytes."""
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('science.orphan_policy must name an absolute materialized JSON path')
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError('orphan policy changed since planning; review and rebuild the plan')
    policy = json.loads(content)
    validate_orphan_policy(policy)
    return policy, digest


def _orphan_surface(point, primitive):
    """Closest XY point and interpolated Z on a measured local simplex."""
    import numpy as np
    if len(primitive) == 1:
        return primitive[0]
    if len(primitive) == 2:
        delta = primitive[1] - primitive[0]
        norm = float(delta[:2] @ delta[:2])
        if norm == 0:
            norm = float(delta @ delta)
            t = float((point - primitive[0]) @ delta) / norm if norm else 0
        else:
            t = float((point[:2] - primitive[0, :2]) @ delta[:2]) / norm
        return primitive[0] + np.clip(t, 0, 1) * delta
    a, b, c = primitive
    matrix = np.column_stack((b[:2] - a[:2], c[:2] - a[:2]))
    try:
        u, v = np.linalg.solve(matrix, point[:2] - a[:2])
        if u >= -1e-10 and v >= -1e-10 and u + v <= 1 + 1e-10:
            return a + u * (b - a) + v * (c - a)
    except np.linalg.LinAlgError:
        pass
    choices = [_orphan_surface(point, primitive[[i, j]]) for i, j in ((0, 1), (1, 2), (2, 0))]
    return min(choices, key=lambda p: (float(np.linalg.norm(p[:2] - point[:2])),
                                       abs(float(p[2] - point[2]))))


def _orphan_footprint(points, link):
    """Local Delaunay simplices, never a global hull; long edges are absent.

    Collinear tracks use adjacent samples. Disconnected islands and curved
    tracks retain their holes when unsupported edges exceed the explicit link.
    Navigation camera centres approximate coverage, not optical field of view.
    """
    import numpy as np
    from scipy.spatial import Delaunay, QhullError
    from shapely.geometry import Point, LineString, Polygon
    from shapely.ops import unary_union
    points = np.unique(np.asarray(points, dtype=float), axis=0)
    if len(points) < 3:
        raise ValueError('at least three distinct measured navigation positions per component are required')
    primitives = [points[[i]] for i in range(len(points))]
    edges = set()
    _, unique_xy = np.unique(points[:, :2], axis=0, return_index=True)
    planar = points[unique_xy]
    try:
        for triangle in Delaunay(planar[:, :2]).simplices:
            p = planar[triangle]
            pairs = ((0, 1), (1, 2), (2, 0))
            if all(np.linalg.norm(p[i] - p[j]) <= link for i, j in pairs):
                primitives.append(p)
            for i, j in pairs:
                edges.add(tuple(sorted((int(unique_xy[triangle[i]]), int(unique_xy[triangle[j]])))))
    except QhullError:
        axis = int(np.argmax(np.ptp(points, axis=0)))
        order = np.argsort(points[:, axis], kind='stable')
        edges.update((int(a), int(b)) for a, b in zip(order, order[1:]))
    for a, b in sorted(edges):
        if np.linalg.norm(points[a] - points[b]) <= link:
            primitives.append(points[[a, b]])
    shapes = []
    for primitive in primitives:
        xy = primitive[:, :2]
        shapes.append(Point(xy[0]) if len(primitive) == 1 else
                      LineString(xy) if len(primitive) == 2 else Polygon(xy))
    return primitives, unary_union(shapes)


def select_pair_orphans(component_members, navigation, orphan_ids, *, epsg, policy):
    """Pure pair-local geometry. Caller supplies measured registration members.

    Navigation records: {identity: {'xyz': [east, north, height], 'epsg': int,
    'vertical_datum': str}}. Missing component poses refuse the entire attempt;
    unknown orphan poses are individually excluded. No global set is mutated.
    """
    import numpy as np
    from shapely.ops import nearest_points
    from scipy.spatial import cKDTree
    validate_orphan_policy(policy)
    if type(epsg) is not int or not (32601 <= epsg <= 32660 or 32701 <= epsg <= 32760):
        raise ValueError('explicit WGS84 UTM EPSG required')
    if len(component_members) != 2:
        raise ValueError('orphan injection requires exactly TWO alignments')
    def pose(identity):
        record = navigation.get(identity)
        if not record:
            raise ValueError('unknown_navigation')
        if record.get('epsg') != epsg or record.get('vertical_datum') != policy['vertical_datum']:
            raise ValueError('navigation_frame_mismatch')
        try:
            xyz = np.asarray(record['xyz'], dtype=float)
            if xyz.shape != (3,) or not np.isfinite(xyz).all():
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise ValueError('unknown_navigation') from None
        return xyz
    footprints = []
    for members in component_members:
        if len(set(members)) < 3:
            raise ValueError('insufficient measured component membership')
        try:
            footprints.append(_orphan_footprint([pose(i) for i in sorted(set(members))],
                                                 policy['footprint_link_m']))
        except ValueError as exc:
            raise ValueError(f'component footprint unavailable: {exc}') from exc
    left, right = nearest_points(footprints[0][1], footprints[1][1])
    # GEOS may choose either endpoint of equally close parallel boundaries.
    # Break those ties with measured vertices so order/platform cannot change
    # which narrow corridor gets offered. Keep the true surface minimum when
    # closest points lie in edge interiors rather than at measured vertices.
    from shapely.geometry import Point
    vertices = [np.unique(np.array([pose(i)[:2] for i in sorted(set(m))]), axis=0)
                for m in component_members]
    distances, indices = cKDTree(vertices[1]).query(vertices[0])
    candidates = [(left.distance(right), (left.x, left.y), (right.x, right.y))]
    candidates.extend((float(d), tuple(a), tuple(vertices[1][j]))
                      for a, d, j in zip(vertices[0], distances, indices))
    _, axy, bxy = min(candidates, key=lambda item: (round(item[0], 7), item[1], item[2]))
    left, right = Point(axy), Point(bxy)
    ends = []
    for endpoint, (primitives, _) in zip((left, right), footprints):
        q = np.array([endpoint.x, endpoint.y, 0.0])
        choices = [_orphan_surface(q, p) for p in primitives]
        minimum = min(float(np.linalg.norm(p[:2] - q[:2])) for p in choices)
        ends.append(np.unique([p for p in choices if np.linalg.norm(p[:2] - q[:2]) <= minimum + 1e-7], axis=0))
    a, b = min(((a, b) for a in ends[0] for b in ends[1]),
               key=lambda pair: (float(np.linalg.norm(pair[1] - pair[0])), tuple(pair[0]), tuple(pair[1])))
    corridor = np.array([a, b]) if np.linalg.norm(b - a) <= policy['max_corridor_m'] else None
    offered, excluded, reasons = [], [], {}
    covered = set().union(*(set(m) for m in component_members))
    spatial = []
    for primitives, _ in footprints:
        centers = np.array([p[:, :2].mean(axis=0) for p in primitives])
        radius = max(float(np.max(np.linalg.norm(p[:, :2] - center, axis=1)))
                     for p, center in zip(primitives, centers))
        spatial.append((cKDTree(centers), radius + policy['horizontal_margin_m'] + 1e-8))
    for identity in sorted(set(orphan_ids)):
        reason = None
        if identity in covered:
            reason = 'already_registered'
        try:
            q = pose(identity)
        except ValueError as exc:
            reason = str(exc)
        if reason is None:
            for index, (primitives, _) in enumerate(footprints):
                tree, radius = spatial[index]
                for candidate in sorted(tree.query_ball_point(q[:2], radius)):
                    primitive = primitives[candidate]
                    near = _orphan_surface(q, primitive)
                    if (np.linalg.norm(q[:2] - near[:2]) <= policy['horizontal_margin_m'] + 1e-8
                            and abs(q[2] - near[2]) <= policy['vertical_margin_m'] + 1e-8):
                        reason = f'within_footprint_{index + 1}'
                        break
                if reason:
                    break
            if reason is None and corridor is not None:
                near = _orphan_surface(q, corridor)
                if (np.linalg.norm(q[:2] - near[:2]) <= policy['horizontal_margin_m'] + 1e-8
                        and abs(q[2] - near[2]) <= policy['vertical_margin_m'] + 1e-8):
                    reason = 'between_footprints'
            reason = reason or 'outside_pair_support'
        reasons[identity] = reason
        (offered if reason.startswith('within_') or reason == 'between_footprints' else excluded).append(identity)
    return {'algorithm': ORPHAN_SELECTOR_VERSION, 'epsg': epsg, 'policy': dict(policy),
            'component_members': [sorted(set(m)) for m in component_members],
            'offered_ids': offered, 'excluded_ids': excluded, 'spatial_reasons': reasons,
            'corridor_xyz': corridor.tolist() if corridor is not None else None,
            'refused': len(offered) > policy['max_offered'],
            'refusal': 'max_offered_exceeded' if len(offered) > policy['max_offered'] else None}


def measured_component_ids(component):
    """Re-read an actual registration census; a count/manifest is insufficient."""
    stem = Path(component['rsalign']).stem
    # Registration indices need not start at zero for an input component.
    path = Path(component['rsalign']).parent / 'identity' / (stem + '.csv')
    with path.open(encoding='utf-8-sig', newline='') as stream:
        header = re.fullmatch(r'#cameras\s+(\d+)\s*', stream.readline().strip())
        rows = [r for r in csv.reader(stream, strict=True) if r and not r[0].startswith('#')]
    if not header or int(header[1]) != component['camera_count'] or len(rows) != int(header[1]):
        raise ValueError('component registration census disagrees with camera count')
    members = [_orphan_id(r[0]) for r in rows]
    if not all(members) or set(members) != {_orphan_id(i) for i in component.get('images', [])}:
        raise ValueError('component manifest differs from measured registration membership')
    return members


def orphan_probe_plan():
    """A controlled probe contract, NOT a claim that this CLI lane was tested.

    Use two small components at original export locations and a fresh owned
    instance/cache. Include one inside orphan, one corridor orphan (approved mask optional),
    and one remote negative control. Preserve pre/post registration exports.
    Never probe on a source tree; all added images are verified attempt copies.
    """
    return {'status': 'unverified', 'selector_version': ORPHAN_SELECTOR_VERSION,
            'policy_fields': {'horizontal_margin_m': 'explicit navigation uncertainty around XY support',
                              'vertical_margin_m': 'explicit uncertainty around interpolated navigation height',
                              'footprint_link_m': 'maximum 3D edge joining measured camera centres',
                              'max_corridor_m': 'maximum 3D length of the closest-footprint corridor',
                              'max_offered': 'positive hard count cap; overflow refuses, never truncates',
                              'vertical_datum': 'declared datum of the selected flight-log height in metres',
                              'component_features': 'explicit 0, 1 or 2; orphans separately use 2',
                              'cli_probe_evidence': 'optional absolute project-owned passed probe JSON'},
            'checks': ['orphan_priors_only', 'component_poses_preserved_before_align',
                       'separate_feature_modes', 'mask_selection_exact',
                       'registration_identity_exact', 'output_frame_preserved'],
            'procedure': [
                'Import exactly two components; export their registration before adding images.',
                'Set the explicit component feature mode while only imported inputs exist.',
                'Add offered.imagelist; import orphan-only priors; attach each mask by literal full-path selection.',
                'Select offered paths only and set feature source 2; capture measured masks/features/priors.',
                'Re-export component registrations BEFORE align; confirm estimated poses did not change.',
                'Align once; measure registration identities, retained original cameras and output CRS.',
                'Confirm the remote control was never added and no source bytes/sidecars changed.',
                'Capture before/prepared/aligned measurements and expected controls with SHA256 bindings.',
                'Use python -m testing.rs_merge_orphan_probe plan/prepare/record/verify; native replay computes checks.'],
            'capture_limit': 'Native capture adapter remains unverified. There is no documented '
                'exportSelectedInputs command. Missing feature/mask readback must fail, never be '
                'filled from dispatched commands.',
            'capture_schema': {
                'schema': 1, 'selector_version': ORPHAN_SELECTOR_VERSION,
                'artifacts': 'expected, before, prepared, aligned: each {path, sha256}',
                'dependencies': 'list of {path, sha256}; current merge driver, merge batch, '
                    'RealityScanCLI, boot/abort helpers and pinned RS executable are mandatory',
                'expected': 'policy, epsg, component_members (exactly two measured lists), navigation, '
                    'orphan_ids (inside, between and remote controls), images {id:{path,sha256}}, '
                    'masks {id:{path,sha256}}, orphan_priors {id:{x,y,z,...}}, '
                    'source_files [{path,sha256}], source_snapshots [{root,fingerprint}]',
                'measurement': 'inputs [{path,priors:{x,y,z,yaw,pitch,roll,accuracy:[6],'
                    'position_prior:bool,orientation_prior:bool},feature_source,mask_path}], '
                    'components [{members:[{path,pose:[x,y,z,r00,...,r22]}]}], '
                    'epsg, vertical_datum; prepared is captured BEFORE alignment; '
                    'all fields must be read back, not inferred from command success'}}


def replay_orphan_probe(capture_manifest, project_root, *, policy=None, epsg=None, executable=None):
    """Read-only replay of measurements, never trust stored verdicts/checkboxes.

    This is a capture-adapter contract, not a claim that RS exposes these fields
    in one native export. An adapter must preserve measured input settings and
    component poses; absent readback is a failure. Synthetic fixtures exercise
    this validator only. No live capture or RS subprocess is implemented here.
    """
    from modules.source_inventory import file_hash, source_fingerprint
    project_root = Path(project_root).resolve()
    identities = []

    def read_bound(record, *, owned=False, parse=False):
        path = Path(record['path'])
        if not path.is_absolute():
            raise ValueError('orphan probe artifact path must be absolute')
        path = path.resolve()
        if owned and not path.is_relative_to(project_root):
            raise ValueError('orphan probe artifact must be project-owned')
        digest = file_hash(path)
        if digest != record['sha256']:
            raise ValueError('orphan probe artifact content changed: ' + str(path))
        identities.append({'path': str(path), 'sha256': digest})
        return json.loads(path.read_text(encoding='utf-8')) if parse else path

    capture_manifest = Path(capture_manifest).resolve()
    manifest = read_bound({'path': str(capture_manifest), 'sha256': file_hash(capture_manifest)},
                          owned=True, parse=True)
    if manifest.get('schema') != 1 or manifest.get('selector_version') != ORPHAN_SELECTOR_VERSION:
        raise ValueError('unsupported orphan probe capture schema')
    records = manifest['artifacts']
    expected, before, prepared, aligned = [read_bound(records[key], owned=True, parse=True)
                                            for key in ('expected', 'before', 'prepared', 'aligned')]
    validate_orphan_policy(expected['policy'])
    if epsg is not None and expected['epsg'] != epsg:
        raise ValueError('orphan probe was captured for a different UTM frame')
    if policy is not None and any(expected['policy'][key] != policy[key]
                                 for key in ORPHAN_POLICY_SCHEMA['required']):
        raise ValueError('orphan probe was captured for a different policy')
    dependencies = {read_bound(record) for record in manifest['dependencies']}
    scripts = Path(__file__).resolve().parent / 'modules/realityscan_interface/RS_CLI/Scripts'
    required = {Path(__file__).resolve(), scripts.parent.parent / 'realityscan_cli.py'}
    required.update(scripts / name for name in ('MergeZoneComponents.bat', 'startRealityScan.bat',
                                               'RuntimeAbortGuard.bat', 'SetVariables.bat'))
    executable = executable or os.environ.get('RS_EXECUTABLE')
    if not executable or Path(executable).resolve() not in dependencies or not required <= dependencies:
        raise ValueError('orphan probe dependencies must bind the current workflow and RS_EXECUTABLE')
    for record in expected['source_files']:
        read_bound(record)
    if not expected['source_files']:
        raise ValueError('orphan probe requires source content controls')
    snapshots = expected['source_snapshots']
    if not snapshots:
        raise ValueError('orphan probe requires source tree snapshots')
    for snapshot in snapshots:
        root = Path(snapshot['root'])
        if not root.is_absolute() or source_fingerprint(root) != snapshot['fingerprint']:
            raise ValueError('orphan probe source tree changed')
        identities.append({'source_root': str(root.resolve()), 'fingerprint': snapshot['fingerprint']})
    if any(not any(Path(record['path']).resolve().is_relative_to(Path(s['root']).resolve())
                   for s in snapshots) for record in expected['source_files']):
        raise ValueError('orphan probe source controls lack tree coverage')
    images = expected['images']
    for name, record in images.items():
        path = read_bound(record, owned=True)
        if _orphan_id(path) != name:
            raise ValueError('orphan probe image identity mismatch')
    if len({record['sha256'] for record in images.values()}) != len(images):
        raise ValueError('orphan probe images contain duplicate content')
    for name, record in expected['masks'].items():
        if name not in images:
            raise ValueError('orphan probe mask references unknown image')
        read_bound(record, owned=True)
    spatial = select_pair_orphans(expected['component_members'], expected['navigation'],
        expected['orphan_ids'], epsg=expected['epsg'], policy=expected['policy'])
    original = set().union(*map(set, expected['component_members']))
    offered = set(spatial['offered_ids'])
    wanted = original | offered
    if set(images) != original | set(expected['orphan_ids']):
        raise ValueError('orphan probe expected image set differs from measured controls')
    for name in offered:
        prior = expected['orphan_priors'].get(name, {})
        if ([prior.get(k) for k in ('x', 'y', 'z')] != expected['navigation'][name]['xyz']
                or prior.get('position_prior') is not True):
            raise ValueError('orphan probe expected priors differ from navigation')

    def inputs(snapshot):
        result = {}
        for row in snapshot['inputs']:
            name = _orphan_id(row['path'])
            if name in result or name not in images or Path(row['path']).resolve() != Path(images[name]['path']).resolve():
                raise ValueError('orphan probe input identity ambiguous or redirected')
            priors = row.get('priors', {})
            if not all(type(priors.get(k)) in (int, float) and math.isfinite(priors[k])
                       for k in ('x', 'y', 'z', 'yaw', 'pitch', 'roll')):
                raise ValueError('orphan probe input prior readback incomplete')
            accuracy = priors.get('accuracy')
            if (not isinstance(accuracy, list) or len(accuracy) != 6
                    or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in accuracy)
                    or any(type(priors.get(k)) is not bool for k in ('position_prior', 'orientation_prior'))):
                raise ValueError('orphan probe prior accuracy/availability readback incomplete')
            if ((snapshot is not before or row.get('feature_source') is not None)
                    and (type(row.get('feature_source')) is not int or row['feature_source'] not in (0, 1, 2))):
                raise ValueError('orphan probe feature readback missing')
            if 'mask_path' not in row or (row['mask_path'] is not None and not isinstance(row['mask_path'], str)):
                raise ValueError('orphan probe mask readback missing')
            result[name] = row
        return result

    def components(snapshot):
        result = []
        for component in snapshot['components']:
            members = {}
            for row in component['members']:
                name = _orphan_id(row['path'])
                pose = row['pose']
                if (name in members or name not in images
                        or Path(row['path']).resolve() != Path(images[name]['path']).resolve()
                        or len(pose) != 12 or any(type(v) not in (int, float) or not math.isfinite(v) for v in pose)):
                    raise ValueError('orphan probe component pose/identity readback incomplete')
                members[name] = pose
            if not members:
                raise ValueError('orphan probe empty component')
            result.append(members)
        return sorted(result, key=lambda item: tuple(sorted(item)))

    b, p, a = [inputs(s) for s in (before, prepared, aligned)]
    bc, pc, ac = [components(s) for s in (before, prepared, aligned)]
    registered = set().union(*(set(c) for c in ac)) if ac else set()
    reasons = set(spatial['spatial_reasons'].values())
    frame = lambda s: (s['epsg'], s['vertical_datum'])
    def mask_matches(name, row):
        record = expected['masks'].get(name)
        return (row['mask_path'] is None if record is None else
                isinstance(row['mask_path'], str) and
                Path(row['mask_path']).resolve() == Path(record['path']).resolve())
    checks = {
        'spatial_controls_exact': not spatial['refused'] and bool(offered) and
            'between_footprints' in reasons and any(r.startswith('within_footprint_') for r in reasons) and
            'outside_pair_support' in reasons and set(b) == original and set(p) == wanted and set(a) == wanted,
        'orphan_priors_only': all(n in p and p[n]['priors'] == row['priors'] for n, row in b.items()) and
            set(expected['orphan_priors']) == offered and all(n in p and
                p[n]['priors'] == expected['orphan_priors'][n] for n in offered),
        'component_poses_preserved_before_align': bc == pc and
            sorted([sorted(c) for c in bc]) == sorted([sorted(c) for c in expected['component_members']]),
        'separate_feature_modes': all(p[n]['feature_source'] == (2 if n in offered else
            expected['policy']['component_features']) for n in p),
        'mask_selection_exact': all(mask_matches(n, row) for n, row in p.items()),
        'registration_identity_exact': original <= registered <= wanted and
            any(set(c) & offered and set(c) & original for c in ac),
        'output_frame_preserved': all(frame(s) == (expected['epsg'], expected['policy']['vertical_datum'])
                                      for s in (before, prepared, aligned)),
        'source_content_unchanged': True,  # All declared source bytes were rehashed above.
    }
    return {'schema': 2, 'status': 'passed' if all(checks.values()) else 'failed',
            'checks': checks, 'failures': sorted(k for k, value in checks.items() if not value),
            'spatial_evidence': spatial, 'dependencies': identities,
            'fingerprint': hashlib.sha256(json.dumps(identities, sort_keys=True).encode()).hexdigest()}


def write_orphan_probe_evidence(capture_manifest, output_path, project_root):
    """Generate GUI-consumable evidence from capture artifacts; no manual approval field."""
    from modules.source_inventory import file_hash
    output = Path(output_path).resolve()
    project = Path(project_root).resolve()
    if not output.is_relative_to(project) or output.exists():
        raise ValueError('orphan probe evidence must be a new project-owned file')
    result = replay_orphan_probe(capture_manifest, project)
    evidence = {'schema': 2, 'capture_manifest': {'path': str(Path(capture_manifest).resolve()),
        'sha256': file_hash(capture_manifest)}, 'validation': result}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(evidence, stream, indent=2, allow_nan=False)
    return result


def validate_orphan_probe_evidence(path, project_root, *, policy=None, epsg=None):
    """Replay the linked measurements; a cached passed verdict has no authority."""
    from modules.source_inventory import file_hash
    path, project = Path(path).resolve(), Path(project_root).resolve()
    if not path.is_relative_to(project):
        raise ValueError('orphan probe evidence must be project-owned')
    evidence = json.loads(path.read_text(encoding='utf-8'))
    if evidence.get('schema') == 3:
        from modules.orphan_import_probe import verify
        record = evidence['recording_manifest']
        result = verify(record['path'], record['sha256'], policy=policy, epsg=epsg)
        if Path(result['project_root']).resolve() != project or result['status'] != 'passed':
            raise ValueError('native orphan probe is incomplete or belongs to another project')
        return result
    if evidence.get('schema') != 2 or not isinstance(evidence.get('capture_manifest'), dict):
        raise ValueError('orphan CLI probe requires replayable schema 2 evidence, not manual checks')
    record = evidence['capture_manifest']
    if file_hash(record['path']) != record['sha256']:
        raise ValueError('orphan probe capture manifest content changed')
    result = replay_orphan_probe(record['path'], project, policy=policy, epsg=epsg)
    if result['status'] != 'passed':
        raise ValueError('orphan CLI probe checks failed: ' + ', '.join(result['failures']))
    return result


def load_project_occlusion(selection_path=None, *, batch_root=None, env=None):
    """Read current shared approval and canonical generated masks; never write.

    Legacy native callers without a project selection remain compatible. An
    explicit selection (including the probe) always requires Apply or Skip.
    """
    environment = os.environ if env is None else env
    selected = selection_path or environment.get('RS_SELECTION_MANIFEST')
    if not selected:
        return None
    from modules import project_occlusion
    selection_path = Path(selected).resolve()
    ambient = environment.get('RS_SELECTION_MANIFEST')
    if ambient and Path(ambient).resolve() != selection_path:
        raise ValueError('Occlusion selection differs from native RS_SELECTION_MANIFEST')
    manifest_value = environment.get('RS_OCCLUSION_MANIFEST')
    expected_sha = environment.get('RS_OCCLUSION_MANIFEST_SHA256', '')
    if not manifest_value or not re.fullmatch('[0-9a-f]{64}', expected_sha):
        raise ValueError('Project native operation requires approved RS_OCCLUSION_MANIFEST and SHA256')
    project_arguments = {}
    if env is not None:
        if not environment.get('RS_PROJECT_FILE'):
            raise ValueError('Explicit project environment requires RS_PROJECT_FILE')
        project_arguments['project_file'] = environment['RS_PROJECT_FILE']
    decision = project_occlusion.validate_external(manifest_value, expected_sha,
                                                   str(selection_path), batch_root=batch_root, **project_arguments)
    root = Path(decision['project_root'])
    manifest_path = (root / decision['canonical_manifest']).resolve()
    selection = json.loads(selection_path.read_text(encoding='utf-8'))
    images = {_orphan_id(row['path']): row for row in selection['images']}
    masks, canonical_ids = {}, {}
    for row in decision['mappings']:
        source = row.get('image')
        if not isinstance(source, dict):
            raise ValueError('Canonical mask lacks the verified selected image path/hash')
        image_path = (root / source['path']).resolve()
        name = _orphan_id(image_path)
        if (name not in images or image_path != Path(images[name]['path']).resolve()
                or source['sha256'] != images[name]['sha256']):
            raise ValueError('Canonical mask differs from selected image identity/content')
        if name in masks:
            raise ValueError('Conflicting canonical masks for one image')
        mask = (root / row['mask']['path']).resolve()
        masks[name] = {'path': str(mask), 'sha256': row['mask']['sha256']}
        canonical_ids[name] = row['image_id']
    return {'manifest': {'path': str(manifest_path), 'sha256': expected_sha},
            'selection_manifest': str(selection_path), 'project_id': decision['project_id'],
            'selection_hash': decision['selection_hash'], 'batch_fingerprint': decision['batch_fingerprint'],
            'decision': decision['decision'], 'masks': masks,
            'canonical_ids': canonical_ids}


def load_orphan_context(selection_path, policy_path, components, *, expected_policy_sha256=None,
                        recording_probe=False, cancelled=None, env=None):
    """Read approved project selection, current hashes and measured membership.

    The policy JSON supplies every geometry margin, vertical datum and component
    feature mode. Optional cli_probe_evidence names a project-owned evidence JSON
    matching orphan_probe_plan(); without it attempts are prepared but refused.
    """
    from modules.project_reviews import ReviewStore
    from modules.source_inventory import approval_token, file_hash as hash_file, _check_cancelled
    def file_hash(path):
        return hash_file(path, cancelled=cancelled)
    _check_cancelled(cancelled)
    from modules.image_batcher.batch_directory import validate_selection_manifest
    policy, _ = read_orphan_policy(policy_path, expected_sha256=expected_policy_sha256)
    selection_path, policy_path = Path(selection_path).resolve(), Path(policy_path).resolve()
    selection = json.loads(selection_path.read_text(encoding='utf-8'))
    validate_selection_manifest(selection_path, selection['images_root'], selection['flight_log'], cancelled=cancelled)
    project_root = next((p for p in selection_path.parents if (p / '.rovscan-owner.json').is_file()), None)
    if project_root is None or not selection_path.is_relative_to(project_root / 'proc'):
        raise ValueError('orphan selection must belong to an owned project proc tree')
    owner = json.loads((project_root / '.rovscan-owner.json').read_text(encoding='utf-8'))
    if selection.get('project_id') != owner.get('project_id'):
        raise ValueError('orphan selection project ownership mismatch')
    project = SimpleNamespace(root=project_root, project_id=owner['project_id'],
                              resolve_path=lambda p: project_root / p)
    store = ReviewStore(project)
    inventory = store.selection()
    if selection.get('selection_hash') != approval_token(inventory):
        raise ValueError('orphan selection is stale')
    for name in ('quality', 'spatial'):
        if selection.get(name + '_review_hash') != store.require_approved(name)['assessment_hash']:
            raise ValueError(f'orphan {name} approval changed')
    root = Path(selection['images_root']).resolve()
    if not root.is_relative_to(selection_path.parent):
        raise ValueError('orphan selected images must be project-owned copies')
    images, masks = {}, {}
    for item in inventory:
        _check_cancelled(cancelled)
        if item.kind != 'image' or not item.included or item.duplicate_of:
            continue
        path = root / item.camera / Path(item.path).name
        identity = _orphan_id(path)
        if identity in images or not path.resolve().is_relative_to(root) or file_hash(path) != item.sha256:
            raise ValueError('orphan image identity ambiguous, redirected or content changed')
        images[identity] = {'path': str(path), 'sha256': item.sha256}
    listed = {str(Path(i['path']).resolve()): i['sha256'] for i in selection['images']}
    if len(listed) != len(selection['images']) or listed != {i['path']: i['sha256'] for i in images.values()}:
        raise ValueError('orphan manifest membership does not match current approved selection')
    environment = os.environ if env is None else env
    occlusion = (load_project_occlusion(selection_path, env=env) if recording_probe or
                 environment.get('RS_SELECTION_MANIFEST') or environment.get('RS_OCCLUSION_MANIFEST') else None)
    by_path = {i.path: i for i in inventory}
    for item in ([] if occlusion is not None else inventory):
        if item.kind != 'mask' or not item.included:
            continue
        image = by_path[item.mask_for]
        image = by_path[image.duplicate_of] if image.duplicate_of else image
        identity = _orphan_id(image.path)
        path = root / image.camera / (Path(image.path).name + '.mask' + Path(item.path).suffix)
        if identity in masks or not path.resolve().is_relative_to(root) or file_hash(path) != item.sha256:
            raise ValueError('orphan mask identity ambiguous, redirected or content changed')
        masks[identity] = {'path': str(path), 'sha256': item.sha256}
    listed_masks = {str(Path(i['path']).resolve()): i['sha256'] for i in selection.get('masks', [])}
    if occlusion is not None:
        if listed_masks:
            raise ValueError('Native project selections must retire source masks before batching')
        masks = occlusion['masks']
    elif listed_masks != {i['path']: i['sha256'] for i in masks.values()}:
        raise ValueError('orphan mask manifest differs from approved inventory')
    flight_log = Path(selection['flight_log']).resolve()
    epsg = selection['epsg']
    zone = utm_zone_from_flight_log_name(str(flight_log))
    if (not flight_log.is_relative_to(selection_path.parent) or zone is None or epsg_for_utm_zone(*zone) != epsg
            or file_hash(flight_log) != selection['flight_log_sha256']):
        raise ValueError('orphan navigation changed or has a different UTM frame')
    with flight_log.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.reader(stream, delimiter=';')
        header = next(reader)
        rows = {}
        for row in reader:
            _check_cancelled(cancelled)
            if not row:
                continue
            identity = _orphan_id(row[0])
            if identity in rows or identity not in images or len(row) != len(header):
                raise ValueError('orphan navigation has duplicate/unknown/incomplete identities')
            rows[identity] = row
    if len(header) != 14 or header[0].casefold() != 'filename':
        raise ValueError('orphan navigation requires the explicit 14-column camera flight log')
    navigation = {}
    for identity, row in rows.items():
        try:
            xyz = [float(v) for v in row[1:4]]
        except ValueError:
            xyz = None
        navigation[identity] = {'xyz': xyz, 'epsg': epsg, 'vertical_datum': policy['vertical_datum']}
    registered = set()
    for component in components:
        _check_cancelled(cancelled)
        registered.update(measured_component_ids(component))
    if not registered <= images.keys():
        raise ValueError('registered component members are absent from the approved selection')
    probe = orphan_probe_plan()
    probe_identity = None
    probe_replay = None
    if policy.get('cli_probe_evidence') and not recording_probe:
        path = Path(policy['cli_probe_evidence']).resolve()
        probe_replay = validate_orphan_probe_evidence(path, project_root, policy=policy, epsg=epsg)
        probe_identity = align_fingerprint.file_identity(str(path))
    from modules import camera_registry
    calibration_profiles = {n: (camera_registry.calibration_xmp(camera) if camera else None)
                            for n in images for camera in [camera_registry.identify(n)]}
    fingerprint = {'algorithm': ORPHAN_SELECTOR_VERSION, 'policy': policy,
                   'policy_file': align_fingerprint.file_identity(str(policy_path)),
                   'selection': align_fingerprint.file_identity(str(selection_path)),
                   'navigation': align_fingerprint.file_identity(str(flight_log)),
                   'images': images, 'masks': masks, 'occlusion': occlusion,
                   'calibration_profiles': calibration_profiles,
                   'cli_probe': probe_identity,
                   'cli_probe_replay': probe_replay['fingerprint'] if probe_replay else None}
    return {'policy': policy, 'epsg': epsg, 'images': images, 'masks': masks,
            'calibration_profiles': calibration_profiles, 'occlusion': occlusion,
            'navigation': navigation, 'rows': rows, 'header': header,
            'registered': registered, 'fingerprint': fingerprint,
            'cli_ready': probe_identity is not None, 'probe_plan': probe,
            'project_root': str(project_root),
            'flight_log': str(flight_log), 'zone': zone, 'review_store': store,
            'selection_hash': selection['selection_hash']}


def prepare_orphan_attempt(context, subset, directory, *, scene_capacity=None):
    """Fresh immutable input copies/lists; never write beside selected sources."""
    from modules.source_inventory import file_hash
    if context.get('occlusion') is not None:
        if load_project_occlusion(context['occlusion']['selection_manifest']) != context['occlusion']:
            raise ValueError('Approved occlusion decision changed before orphan attempt')
    if 'review_store' in context:
        from modules.source_inventory import approval_token
        if approval_token(context['review_store'].selection()) != context['selection_hash']:
            raise ValueError('orphan selection approvals changed before attempt')
        for key in ('selection', 'navigation', 'policy_file', 'cli_probe'):
            original = context['fingerprint'][key]
            if original is not None and align_fingerprint.file_identity(original['path']) != original:
                raise ValueError('orphan provenance changed before attempt: ' + key)
        if context['cli_ready']:
            replay = validate_orphan_probe_evidence(context['policy']['cli_probe_evidence'],
                context['project_root'], policy=context['policy'], epsg=context['epsg'])
            if replay['fingerprint'] != context['fingerprint']['cli_probe_replay']:
                raise ValueError('orphan probe provenance changed before attempt')
    members = [measured_component_ids(c) for c in subset]
    candidates = set(context['images']) - context['registered']
    if candidates:
        evidence = select_pair_orphans(members, context['navigation'], candidates,
                                       epsg=context['epsg'], policy=context['policy'])
    else:
        evidence = dict(algorithm=ORPHAN_SELECTOR_VERSION, epsg=context['epsg'], policy=dict(context['policy']),
                        component_members=members, offered_ids=[], excluded_ids=[], spatial_reasons={},
                        refused=False, refusal=None)
    evidence['cli_status'] = 'probe_evidence_supplied' if context['cli_ready'] else 'probe_required'
    if scene_capacity is not None and len(evidence['offered_ids']) > scene_capacity:
        evidence.update(refused=True, refusal='orphan_scene_ceiling_exceeded')
    directory = Path(directory)
    directory.mkdir(exist_ok=False)
    if not evidence['offered_ids']:
        evidence.update(cli_status='not_required', reason='no_pair_local_orphans')
    elif not context['cli_ready']:
        evidence.update(refused=True, refusal='orphan_cli_probe_required', controlled_probe=context['probe_plan'])
    evidence_path = directory / 'orphan_selection.json'
    evidence_path.write_text(json.dumps(evidence, indent=2, allow_nan=False), encoding='utf-8')
    if evidence['refused'] or not evidence['offered_ids']:
        return evidence, None
    return evidence, stage_orphan_inputs(context, evidence['offered_ids'], directory)


def stage_orphan_inputs(context, offered_ids, directory):
    """Copy already-scoped pixels/priors; no RS execution or readiness assertion.

    The production caller gates on probe evidence; the tiny recorder calls this
    data-only helper after pinning its reviewed geometry and control selection.
    """
    from modules.source_inventory import file_hash
    from modules import camera_registry
    directory = Path(directory)
    calibrations = {}
    if 'calibration_profiles' in context:
        stems = set()
        for identity in offered_ids:
            camera = camera_registry.identify(identity)
            content = context['calibration_profiles'].get(identity)
            if camera is None or content is None:
                raise ValueError('Offered orphan has no approved native calibration profile: ' + identity)
            camera_registry.validate_calibration_xmp(content, camera)
            stem = Path(context['images'][identity]['path']).stem.casefold()
            if stem in stems:
                raise ValueError('Orphan calibration sidecar stem collision')
            stems.add(stem)
            calibrations[identity] = content
    images = directory / 'images'
    images.mkdir()
    paths, mask_lines, rows = [], [], []
    for identity in offered_ids:
        item = context['images'][identity]
        source = Path(item['path'])
        target = images / source.name
        # Never inherit solved pose XMP. New inputs receive native calibration only.
        for value in (str(source), str(target)):
            if not value.isascii() or any(c in value for c in '&|<>^%!"\'\r\n\t'):
                raise ValueError('orphan CLI paths must be ASCII without cmd metacharacters')
        if file_hash(source) != item['sha256']:
            raise ValueError('orphan image changed before staging')
        shutil.copyfile(source, target)
        if file_hash(target) != item['sha256']:
            raise ValueError('orphan image changed during staging')
        if identity in calibrations:
            with target.with_suffix('.xmp').open('x', encoding='utf-8') as stream:
                stream.write(calibrations[identity])
        paths.append(str(target))
        row = list(context['rows'][identity])
        if not all(math.isfinite(float(v)) for v in row[1:]):
            raise ValueError('orphan priors contain unknown/nonfinite fields')
        row[0] = str(target)
        rows.append(row)
        if identity in context['masks']:
            mask = context['masks'][identity]
            output = images / (source.name + '.mask' + Path(mask['path']).suffix)
            if file_hash(Path(mask['path'])) != mask['sha256']:
                raise ValueError('orphan mask changed before staging')
            shutil.copyfile(mask['path'], output)
            if file_hash(output) != mask['sha256']:
                raise ValueError('orphan mask changed during staging')
            mask_lines.append(str(target) + '|' + str(output))
    def write_list(name, lines):
        path = directory / name
        path.write_bytes(('\r\n'.join(lines) + ('\r\n' if lines else '')).encode('ascii'))
        return str(path)
    inputs = {'list': write_list('offered.imagelist', paths),
              'masks': write_list('masks.txt', mask_lines), 'root': str(images),
              'component_features': context['policy']['component_features']}
    log = directory / Path(context['flight_log']).name
    with log.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream, delimiter=';', lineterminator='\n')
        writer.writerow(context['header'])
        writer.writerows(rows)
    inputs['flight_log'] = str(log)
    inputs['params'] = write_flight_log_params(os.path.join(METADATA_DIR, 'FlightLogParams.xml'),
        str(directory / 'FlightLogParams.xml'), zone=context['zone'][0], band=context['zone'][1])
    inputs['has_orphans'] = bool(paths)
    return inputs

# Escalation ladder - one variable per rung. Order is revisited by the
# D7 probe verdict (testing/MERGE_TEST_PLAN.md "D7 probe wave"): if
# align-rematch is the only content-capable mechanism for duplicate-path
# zones, put it first via rs_settings merge.ladder="content_first".
LADDERS = {
    'merge_first': [
        {'label': 'merge_georef', 'mode': 'merge',
         'settings': ['sfmMergeGeoreferencedComponents:true',
                      'sfmEnableCameraPrior:true']},
        {'label': 'align_rematch', 'mode': 'align',
         'settings': ['sfmMergeGeoreferencedComponents:true',
                      'sfmEnableCameraPrior:true',
                      'sfmForceComponentRematch:true']},
        {'label': 'align_rematch_high_overlap', 'mode': 'align',
         'settings': ['sfmMergeGeoreferencedComponents:true',
                      'sfmEnableCameraPrior:true',
                      'sfmForceComponentRematch:true',
                      'sfmImagesOverlap:High']},
    ],
    'content_first': [
        {'label': 'align_rematch', 'mode': 'align',
         'settings': ['sfmMergeGeoreferencedComponents:true',
                      'sfmEnableCameraPrior:true',
                      'sfmForceComponentRematch:true']},
        {'label': 'align_rematch_high_overlap', 'mode': 'align',
         'settings': ['sfmMergeGeoreferencedComponents:true',
                      'sfmEnableCameraPrior:true',
                      'sfmForceComponentRematch:true',
                      'sfmImagesOverlap:High']},
        {'label': 'merge_georef', 'mode': 'merge',
         'settings': ['sfmMergeGeoreferencedComponents:true',
                      'sfmEnableCameraPrior:true']},
    ],
}


# ----------------------------------------------------------------------
# Manifest / cluster analysis (pure)
# ----------------------------------------------------------------------

def load_inputs(components_root: str, complist: str | None,
                logger) -> list[dict]:
    """Load manifests for every input component. When --complist is
    given, only its .rsalign paths participate (the grow->merge handoff);
    otherwise every manifested export under components_root does.

    Components WITHOUT a manifest are refused: the feature-aware loop is
    driven by membership + bbox, and an anonymous component cannot be
    border-gated, twin-resolved, or attributed. (Re-run AlignZone, or
    merge the pre-growth manifested exports - the H2023 case.)"""
    manifests = component_analysis.load_manifests(components_root)
    by_path = {os.path.normcase(os.path.abspath(m.get('rsalign', ''))): m
               for m in manifests if m.get('rsalign')}
    if complist:
        with open(complist, encoding='utf-8') as f:
            wanted = [l.strip() for l in f if l.strip()]
        # A complist names EXPLICIT paths, which legitimately live outside
        # components_root (fused exports in attempt directories, a hull from
        # an earlier run kept at its original export location per hard rule
        # 7). For any entry the root scan did not surface, look for the
        # manifest BESIDE the file before refusing - discovery scope, not
        # manifest absence, is what used to fail here (2026-07-28: phase-2
        # assembly aborted with 'without manifests' for three components
        # whose manifests all existed).
        for p in wanted:
            norm = os.path.normcase(os.path.abspath(p))
            if norm in by_path:
                continue
            sidecar = p + '.manifest.json'
            if os.path.isfile(sidecar):
                m = component_manifest.load_manifest(sidecar)
                if m.get('rsalign'):
                    by_path[norm] = m
        missing = [p for p in wanted
                   if os.path.normcase(os.path.abspath(p)) not in by_path]
        if missing:
            raise ValueError(
                'complist entries without manifests (feature-aware merge '
                'needs membership): ' + ', '.join(missing))
        picked = [by_path[os.path.normcase(os.path.abspath(p))] for p in wanted]
    else:
        picked = [m for m in manifests if m.get('rsalign')
                  and os.path.isfile(m['rsalign'])]
    for m in picked:
        if not os.path.isfile(m['rsalign']):
            raise FileNotFoundError(f'component missing on disk: {m["rsalign"]}')
    logger.info('%d manifested input components', len(picked))
    return picked


def measure_input_scales(inputs: list[dict], union_log: str, logger,
                         scale_min: float = scale_oracle.DEFAULT_SCALE_MIN,
                         scale_max: float = scale_oracle.DEFAULT_SCALE_MAX) -> dict:
    """Metric scale per INPUT component, keyed by component_key.

    Uses each manifest's own image list against the harvest sitting beside its
    .rsalign, so a component is never mis-identified by ordinal position. The
    union flight log supplies nav for every image regardless of which zone it
    came from.

    `scale_min`/`scale_max` MUST reach the verdict: the operator's
    --scale_min/--scale_max were previously accepted, persisted, printed in
    EVALUATION_READY as the authoritative band - and never applied (audit #5,
    2026-07-28). Every verdict was baked at the 0.90-1.10 defaults, so
    TIGHTENING the gate silently did nothing while the report claimed it.
    """
    nav = scale_oracle.load_nav_positions(union_log)
    out = {}
    for m in inputs:
        key = component_analysis.component_key(m)
        comp_dir = os.path.dirname(m.get('rsalign', '')) or '.'
        try:
            stats = scale_oracle.scale_for_images(m.get('images', []), comp_dir, nav)
        except OSError as exc:
            logger.warning('Scale measurement failed for %s: %s', key, exc)
            stats = None
        status, why = scale_oracle.verdict(stats, scale_min, scale_max)
        out[key] = {'status': status, 'explanation': why,
                    'median': None if stats is None else stats['median'],
                    'iqr_low': None if stats is None else stats['iqr_low'],
                    'iqr_high': None if stats is None else stats['iqr_high'],
                    'cameras_measured': None if stats is None else stats['cameras']}
        line = 'Scale %s: %s - %s'
        if status == 'fail':
            logger.error(line, key, status.upper(), why)
        elif status == 'unmeasured':
            logger.warning(line, key, status.upper(), why)
        else:
            logger.info(line, key, status.upper(), why)
    return out


def apply_scale_gate(targets: list[dict], input_scales: dict,
                     scale_min: float, scale_max: float, logger) -> tuple[list, list]:
    """Drop model targets whose metric scale is out of band or unmeasurable.

    A result component inherits the verdicts of the inputs attributed to it, and
    the WORST one decides: a fused component containing a 0.236 input is not
    salvaged by a sound sibling. UNMEASURED blocks too - the whole point is that
    silence is not evidence, and modelling is the expensive, deliverable-facing
    step. `--scale_gate false` overrides for a deliberate exception.
    """
    kept, blocked = [], []
    for c in targets:
        origin_keys = c.get('inputs') or [c.get('key')]
        verdicts = [input_scales.get(k) for k in origin_keys if k]
        verdicts = [v for v in verdicts if v]
        if not verdicts:
            worst, why = 'unmeasured', 'no scale record for this component'
        elif any(v['status'] == 'fail' for v in verdicts):
            bad = next(v for v in verdicts if v['status'] == 'fail')
            worst, why = 'fail', bad['explanation']
        elif any(v['status'] == 'unmeasured' for v in verdicts):
            bad = next(v for v in verdicts if v['status'] == 'unmeasured')
            worst, why = 'unmeasured', bad['explanation']
        else:
            worst, why = 'pass', '; '.join(v['explanation'] for v in verdicts)
        if worst == 'pass':
            kept.append(c)
            continue
        blocked.append({'key': c.get('key'), 'status': worst, 'reason': why})
        logger.error(
            'SCALE GATE blocked %s from model generation: %s (%s). '
            'Metric scale is not something a camera count can see; re-align '
            'this component or pass --scale_gate false to override.',
            c.get('key'), worst.upper(), why)
    if blocked and not kept:
        logger.error('SCALE GATE blocked EVERY model target - nothing will be '
                     'modelled. Fix the alignment before spending model hours.')
    return kept, blocked



def shared_image_count(a: dict, b: dict) -> int:
    """Shared image basenames between two component manifests (lowercased)."""
    sa = {i.lower() for i in (a.get('images') or [])}
    sb = {i.lower() for i in (b.get('images') or [])}
    return len(sa & sb)


def pair_related(a: dict, b: dict) -> tuple[bool, str]:
    """The owner's uniqueness criterion (2026-07-28): two components belong in
    one merge scene ONLY when they share imagery or genuinely overlap in space.

    Anything else is a unique feature at its own maximum. The previous gate -
    find_borders with 10 m margin on BOTH bboxes, then TRANSITIVE closure -
    chained eight disjoint objects into one scene, and merge_georef rigid-glued
    them into a single 3,615-camera container (merged5 cluster_1: exactly ONE of
    its 28 pairs shared any imagery; RealityScan itself reported 'Finalizing 3'
    then '7' then '8' components while the arithmetic scored each attempt as a
    fusion). A null bbox still relates to everything - conservative direction.
    """
    shared = shared_image_count(a, b)
    if shared:
        return True, f'{shared} shared images'
    ba, bb = a.get('bbox_utm'), b.get('bbox_utm')
    if not ba or not bb:
        return True, 'null bbox - conservative'
    dx = min(ba[2], bb[2]) - max(ba[0], bb[0])
    dy = min(ba[3], bb[3]) - max(ba[1], bb[1])
    if dx > 0 and dy > 0:
        return True, f'true bbox overlap {dx:.1f} x {dy:.1f} m'
    return False, 'no shared imagery, no spatial overlap'


def fused_export_name(tag: str, attempt_no: int) -> str:
    """The ONE name a fused attempt exports under: file stem, manifest
    component and in-scene component are all this string plus `_c<K>`.
    peel_index restarts every attempt, so the attempt number is what makes
    two fusions in one cluster distinct (the 2026-07-28 duplicate-identity
    crash and the wrong-component model hazard)."""
    return f'{tag}_a{attempt_no}'


# Merge-scene camera ceiling (C-20260802-01, ON2026 on the 192 GB box):
# a 34,105-camera merge scene completed at 262 GB peak commit; a ~44k-cam
# scene died inside RealityScan with 0x8007000E E_OUTOFMEMORY at 319.5 GB
# after 5.6 h, and the follow-up rung OOM'd the driver Python itself after
# 19 h. The ceiling is enforced BEFORE launch (an over-ceiling attempt
# wastes unattended hours and can kill the driver) - deliberately a plain
# argparse default, never an rs_settings inheritance (safety constants do
# not silently carry between sessions).
MAX_MERGE_SCENE_CAMERAS = 34_000


def scene_ceiling_verdict(subset: list, ceiling: int) -> tuple:
    """(refuse, total_cameras) for a candidate merge subset. Pure, like
    acceptance_verdict, so the suite drives the real decision."""
    total = sum((m.get('camera_count') or 0) for m in subset)
    return total > ceiling, total


def loss_budget(input_cams: int, loss_tolerance_frac: float) -> int:
    """Absolute camera budget a fusion may drop, from the operator fraction."""
    return int(input_cams * loss_tolerance_frac)


def acceptance_verdict(workflow_success: bool, adopted_count: int,
                       fused: bool, confidence: str,
                       lost: int | None, tol: int) -> tuple[bool, str | None]:
    """(accept, rejection_reason) for one merge attempt.

    Pure so the suite can drive the REAL decision - the earlier tests
    re-implemented this arithmetic and would have kept passing had the
    driver regressed (final review, must-fix #2; the audit-#17 shape).
    """
    accept = bool(workflow_success and adopted_count and fused
                  and confidence == 'exact'
                  and lost is not None and lost <= tol)
    rejection = None
    if workflow_success and adopted_count and lost and lost > tol:
        rejection = 'shrink'
    if workflow_success and fused and confidence != 'exact':
        rejection = 'ambiguous_attribution'
    return accept, rejection


def effective_ladder_for(subset: list[dict], ladder: list[dict]) -> list[dict]:
    """Rungs admissible for this subset: merge rungs only when the
    shared-image graph SPANS it (merge fuses through camera identity and
    otherwise rigid-glues everything in the scene); align rungs always."""
    if shared_graph_spans(subset):
        return ladder
    align_only = [s for s in ladder if s['mode'] == 'align']
    return align_only or ladder


def shared_graph_spans(subset: list[dict]) -> bool:
    """True iff every member is reachable from every other through
    shared-image edges. This is the admission test for -mergeComponents
    rungs: merge fuses through camera identity, so a subset it can act on
    soundly must be identity-connected end to end."""
    if len(subset) < 2:
        return True
    reached = {0}
    frontier = [0]
    while frontier:
        i = frontier.pop()
        for j in range(len(subset)):
            if j not in reached and shared_image_count(subset[i], subset[j]):
                reached.add(j)
                frontier.append(j)
    return len(reached) == len(subset)


def related_pairs(manifests: list[dict], pair_gate: str,
                  logger=None) -> list[tuple[str, str]]:
    """Every related pair under the chosen gate.

    'overlap' (default) = pair_related above. 'border' = the pre-2026-07-28
    find_borders behaviour (10 m margin on both boxes), kept so the two can be
    compared rather than assumed.
    """
    if pair_gate == 'border':
        return [tuple(e['pair'])
                for e in component_analysis.find_borders(manifests)]
    pairs = []
    for i, a in enumerate(manifests):
        for b in manifests[i + 1:]:
            ok, why = pair_related(a, b)
            if ok:
                ka = component_analysis.component_key(a)
                kb = component_analysis.component_key(b)
                pairs.append((ka, kb))
                if logger:
                    logger.info('related: %s <-> %s (%s)', ka, kb, why)
    return pairs


def neighbour_subset(current: list[dict], target_key: str, logger,
                     pair_gate: str = 'overlap') -> list[dict]:
    """`target_key` plus every component related to it under the pair gate."""
    neighbours = set()
    for a, b in related_pairs(current, pair_gate):
        if a == target_key:
            neighbours.add(b)
        elif b == target_key:
            neighbours.add(a)
    keys = {target_key} | neighbours
    return [m for m in current
            if component_analysis.component_key(m) in keys]


def growth_order(current: list[dict]) -> list[str]:
    """Component keys largest-first - the growth order grow_zone also uses.

    Largest first because a big component is the most likely anchor: absorbing a
    fragment into it keeps membership attribution simple, and it front-loads the
    attempts most likely to pay off.
    """
    return [component_analysis.component_key(m)
            for m in sorted(current, key=lambda m: -(m.get('camera_count') or 0))]


def partition_clusters(manifests: list[dict], logger,
                       pair_gate: str = 'overlap') -> tuple[list[list[dict]], dict]:
    """Twin-drop, then connected components of the relatedness graph.

    Returns (clusters, plan). Every returned cluster is a list of
    manifests; singletons are legitimate feature candidates and are
    carried to the assembly stage untouched."""
    plan = component_analysis.merge_plan(manifests)
    discarded = set(plan.get('discards', []))
    survivors = [m for m in manifests
                 if component_analysis.component_key(m) not in discarded]
    for d in discarded:
        logger.warning('Twin drop: %s (no unique images)', d)

    by_key = {component_analysis.component_key(m): m for m in survivors}
    adjacency = {k: set() for k in by_key}
    for a, b in related_pairs(survivors, pair_gate, logger=logger):
        adjacency[a].add(b)
        adjacency[b].add(a)

    clusters, visited = [], set()
    for key in sorted(by_key):
        if key in visited:
            continue
        stack, members = [key], set()
        while stack:
            k = stack.pop()
            if k in members:
                continue
            members.add(k)
            stack.extend(adjacency[k] - members)
        visited |= members
        clusters.append([by_key[k] for k in sorted(members)])
    clusters.sort(key=lambda c: -sum(m['camera_count'] for m in c))
    logger.info('%d survivors partition into %d spatial cluster(s): %s',
                len(survivors), len(clusters),
                [f'{len(c)} comps/{sum(m["camera_count"] for m in c)} cams'
                 for c in clusters])
    return clusters, plan


def attribute_result(input_manifests: list[dict], peel_counts: list[int],
                     logger, loss_tolerance: int = 0,
                     peel_members: list[list[str]] | None = None,
                     offered_members: list[str] | None = None) -> tuple[list[dict], str]:
    """Attribute selected-component registration exports to parent subsets.

    Without peel_members, return count-only candidates with no membership,
    loss or duplicate-collapse certification. With measured memberships,
    accept only subsets covering every observed image within the unique-image
    loss budget. Original source components left in the scene are residuals.
    Ambiguous subsets or bounded-search exhaustion are never certified.
    """
    # Counts identify candidate subsets, never camera membership or retention.
    # Only the selected-component registration export can supply that evidence.
    measured = peel_members is not None
    if measured and (len(peel_members) != len(peel_counts) or any(
            len(names) != count or any(not str(n).strip() for n in names)
            for names, count in zip(peel_members, peel_counts))):
        raise ValueError('registration membership disagrees with peel counts')

    def image_key(name):
        return os.path.basename(str(name).replace('\\', '/')).lower()

    by_key = {component_analysis.component_key(m): m for m in input_manifests}
    offered = {image_key(n) for n in (offered_members or [])}
    if offered and not measured:
        raise ValueError('orphan attribution requires measured registration membership')
    remaining = {k: m['camera_count'] for k, m in by_key.items()}
    basenames = {k: {image_key(i)
                     for i in (m.get('images') or [])}
                 for k, m in by_key.items()}
    if offered & set().union(*basenames.values()):
        raise ValueError('offered orphans include an existing registered member')
    # A manifest with no image list (older exports) cannot be de-duplicated:
    # its unique count is its camera count, exactly the pre-2026-09-06 rule.
    for k, m in by_key.items():
        if not basenames[k]:
            basenames[k] = {f'{k}#{i}' for i in range(m['camera_count'])}
    consumed_counts: list[int] = []
    results, confidence = [], 'exact'

    order = sorted(range(len(peel_counts)), key=lambda i: -peel_counts[i])
    by_index: dict[int, dict] = {}
    for idx in order:
        full_count = peel_counts[idx]
        added = ([image_key(n) for n in peel_members[idx] if image_key(n) in offered]
                 if measured else [])
        count = full_count - len(added)
        observed = ({image_key(n) for n in peel_members[idx]}
                    if measured else None)
        if measured:
            observed -= offered
        if added and count == 0:
            by_index[idx] = {'peel_index': idx, 'camera_count': full_count,
                             'inputs': [], 'members': added, 'residual': True,
                             'offered_registered': added, 'evidence': 'registration'}
            continue
        matched, matched_loss, matched_collapsed = None, 0, 0
        keys = sorted(remaining)
        # (loss, kind, -len, chosen, collapsed, unique, total) per candidate
        # subset. kind: 0 = count is the exact SUM (no copy folded), 1 = count
        # is the exact UNIQUE count (every duplicate folded), 2 = in between
        # (some folded - or a loss smaller than the duplicate count, which
        # this instrument cannot tell apart), 3 = below unique (real loss).
        candidates: list[tuple] = []
        suffix_totals = [0] * (len(keys) + 1)
        suffix_members = [set() for _ in range(len(keys) + 1)]
        for i in range(len(keys) - 1, -1, -1):
            suffix_totals[i] = suffix_totals[i + 1] + remaining[keys[i]]
            suffix_members[i] = suffix_members[i + 1] | basenames[keys[i]]
        search_calls = 0
        search_exhausted = False

        def search(i, chosen, total, union):
            nonlocal search_calls, search_exhausted
            search_calls += 1
            if search_calls > 100_000:
                search_exhausted = True
                return
            if total + suffix_totals[i] < count:
                return
            if measured and not observed <= union | suffix_members[i]:
                return
            if chosen:
                unique = len(union)
                if unique - loss_tolerance > count:
                    return  # every superset has at least this many unique
                if total >= count:
                    if measured:
                        loss = len(union - observed)
                        collapsed = total - count - loss
                        if (observed <= union and loss <= loss_tolerance
                                and collapsed >= 0):
                            kind = 0 if collapsed == 0 else 1
                            candidates.append((loss, kind, -len(chosen), list(chosen),
                                               collapsed, unique, total))
                    elif count == total:
                        kind, loss, collapsed = 0, 0, 0
                    elif count >= unique:
                        kind = 1 if count == unique else 2
                        loss, collapsed = 0, total - count
                    else:
                        kind, loss, collapsed = 3, unique - count, total - unique
                    if not measured:
                        candidates.append((loss, kind, -len(chosen), list(chosen),
                                           collapsed, unique, total))
            if i >= len(keys):
                return
            k = keys[i]
            chosen.append(k)
            search(i + 1, chosen, total + remaining[k], union | basenames[k])
            chosen.pop()
            if not search_exhausted:
                search(i + 1, chosen, total, union)

        if count == suffix_totals[0] and all(remaining[k] > 0 for k in keys):
            # Every proper subset has fewer cameras: one uniquely possible sum.
            search(len(keys), keys, suffix_totals[0], suffix_members[0])
        else:
            search(0, [], 0, set())
        if search_exhausted:
            candidates.clear()
            confidence = 'ambiguous'
            logger.warning('attribution search limit reached; no subset certified')
        if candidates:
            candidates.sort(key=lambda t: (t[0], t[1], t[2]))
            lossless_exact = [c for c in candidates if c[0] == 0 and c[1] in (0, 1)]
            if lossless_exact:
                best = lossless_exact[0]
                if len({tuple(c[3]) for c in lossless_exact}) > 1:
                    confidence = 'ambiguous'
                    logger.warning('attribution ambiguous for count %d: %d '
                                   'candidate subsets, took %s',
                                   count, len(lossless_exact), best[3])
                elif best[1] == 1:
                    logger.info('peel count %d matches %s '
                                '(%d camera(s) summed): %d duplicate '
                                'collapse candidate(s), evidence=%s',
                                count, best[3], best[6], best[4],
                                'registration' if measured else 'count_only')
            elif candidates[0][0] == 0:
                best = candidates[0]
                logger.warning('peel count %d sits between the unique (%d) and '
                               'summed (%d) camera counts of %s - %d possible '
                               'duplicate collapse(s); a '
                               'real loss smaller than the duplicate count is '
                               'indistinguishable from this',
                               count, best[5], best[6], best[3], best[4])
            else:
                # Smallest loss first, then the LARGEST subset, so a genuine
                # fusion beats a lone input that happens to sit within tolerance.
                best = candidates[0]
                tied = [c for c in candidates
                        if c[0] == best[0] and c[2] == best[2]]
                if len({tuple(c[3]) for c in tied}) > 1:
                    confidence = 'ambiguous'
                    logger.warning('lossy attribution ambiguous for count %d: '
                                   '%d candidates at loss %d, took %s',
                                   count, len(tied), best[0], best[3])
                else:
                    logger.info('candidate peel count %d for %s with a '
                                '%d-camera loss estimate (tolerance %d)%s',
                                count, best[3], best[0], loss_tolerance,
                                f', {best[4]} duplicate(s) folded' if best[4] else '')
            matched, matched_loss, matched_collapsed = best[3], best[0], best[4]

        if matched is not None:
            for k in matched:
                consumed_counts.append(remaining.pop(k))
            by_index[idx] = {'peel_index': idx, 'camera_count': full_count,
                             'inputs': matched,
                             'members': ([image_key(n) for n in peel_members[idx]]
                                         if measured else None),
                             'residual': False,
                             'loss': matched_loss if measured else None,
                             'collapsed': matched_collapsed if measured else None,
                             'estimated_loss': matched_loss,
                             'estimated_collapsed': matched_collapsed,
                             'offered_registered': added,
                             'evidence': 'registration' if measured else 'count_only'}
        elif count in consumed_counts and (not measured or any(
                observed == basenames[k] and count == by_key[k]['camera_count']
                for k in by_key if k not in remaining)):
            consumed_counts.remove(count)
            by_index[idx] = {'peel_index': idx, 'camera_count': count,
                             'inputs': [], 'members': None, 'residual': True}
        elif not remaining and count <= loss_tolerance and (not measured or
                observed <= set().union(*basenames.values())):
            # Bounded shed (2026-08-01, ON2026): the joint solve can split
            # weak boundary cameras into a fragment that is not a
            # subset-sum of whole inputs. With EVERY input already
            # attributed and the fragment inside the loss budget, treat it
            # as shed cameras - they are already counted in `lost`
            # (adopted excludes them) and acceptance still enforces
            # lost <= budget on the TOTAL. Without this, any rung that
            # sheds even one fragment can never be accepted (observed:
            # 885 of 36.9k = 2.4% shed on every rung).
            logger.warning('unattributable residual peel of %d cameras is '
                           'within the %d-camera loss budget - treated as '
                           'SHED, not ambiguous', count, loss_tolerance)
            by_index[idx] = {'peel_index': idx, 'camera_count': count,
                             'inputs': [], 'members': None, 'residual': True}
        else:
            confidence = 'ambiguous'
            logger.warning('attribution failed for peel count %d '
                           '(remaining inputs %s)', count, remaining)
            by_index[idx] = {'peel_index': idx, 'camera_count': count,
                             'inputs': [], 'members': None, 'residual': False}

    if remaining:
        confidence = 'ambiguous'
        logger.warning('inputs unattributed after peel: %s', remaining)
    if not measured and confidence == 'exact':
        confidence = 'count_only'
    results = [by_index[i] for i in sorted(by_index)]
    return results, confidence


# ----------------------------------------------------------------------
# Flight-log helpers
# ----------------------------------------------------------------------

def count_unique_images(images_root: str) -> int:
    names = set()
    for root, _dirs, files in os.walk(images_root):
        for f in files:
            if f.lower().endswith(IMAGE_EXTENSIONS):
                names.add(f.lower())
    return len(names)


def build_union_flight_log(images_root: str, output_dir: str, logger,
                           only_basenames: set[str] | None = None,
                           tag: str = '') -> tuple[str, str]:
    """Union of the per-zone flight logs (deduped by image basename;
    optionally filtered to `only_basenames`) + auto-generated CRS XML.
    The merge scene MUST have these constraints imported: a merged
    component is a NEW component and is not georeferenced otherwise
    (observed NA156 H2023)."""
    zone_logs = []
    for root, _dirs, files in os.walk(images_root):
        for f in files:
            if f.lower().startswith('flight_log') and f.lower().endswith('_utm.txt'):
                zone_logs.append(os.path.join(root, f))
    if not zone_logs:
        raise FileNotFoundError(f'No flight_log*_UTM.txt found under {images_root}')

    # os.walk order is not deterministic and, more importantly, not
    # CORRECT: the frame for the whole merge used to be read off
    # zone_logs[0] while the rows were read in sorted() order, so one
    # untagged (or foreign-zone) log anywhere under images_root flipped
    # the entire merge to the local template on a logger.warning - the
    # 2026-08-07 silent mis-frame class _FRAME_INCIDENT exists to prevent
    # (audit 2026-08-07). Sort once, then require unanimity.
    zone_logs = sorted(zone_logs)
    zone_band = assert_one_zone(zone_logs, images_root)

    # No UTM tag in the filename = a LOCAL-frame campaign (e.g. COLMAP
    # local:1 priors, ON2026; C-20260730-05): use the dedicated
    # FlightLogParamsLocal.xml template. Never fall back to the shared
    # UTM template "as-is" - a template carrying the wrong frame imports
    # silently mis-registered (2026-08-07 incident: ON2026's local frame
    # in the shared template poisoned a UTM 57L import; 3/32 registered,
    # exit code 0).
    local_frame = zone_band is None
    if local_frame:
        logger.warning(
            'Flight log "%s" carries no UTM zone tag - LOCAL-frame campaign; '
            'generating params from FlightLogParamsLocal.xml. Verify this '
            'cruise really uses local:1 priors!', os.path.basename(zone_logs[0]))
        zone, band = None, None
    else:
        zone, band = zone_band

    header, rows = None, {}
    for log_path in zone_logs:
        with open(log_path, encoding='utf-8') as f:
            lines = f.read().splitlines()
        if not lines:
            continue
        header = header or lines[0]
        for line in lines[1:]:
            if not line.strip():
                continue
            # `only_basenames` holds BASENAMES, but in pool layout the log's
            # filename column is a full canonical path by design
            # (FLIGHTLOG_ARCHITECTURE), so comparing the raw column matched
            # nothing and every pool-mode merge hit the ZERO-rows refusal
            # below. Observed on NA165/H2060: 1 zone log, 2,285 requested
            # images, 0 matched. Match the raw column first so copy-layout
            # logs carrying bare names are unchanged; key the dedup on the
            # basename, which IS the raw value in copy layout.
            raw = line.split(';')[0].strip('"').strip()
            raw_key = raw.lower()
            base_key = os.path.basename(raw.replace('\\', '/')).lower()
            # ...and the STEM: callers pass manifest `images`, which the
            # identity harvest records WITHOUT an extension, so a basename
            # carrying .jpg still misses. Try every form.
            candidates = (raw_key, base_key,
                          os.path.splitext(raw_key)[0],
                          os.path.splitext(base_key)[0])
            if (only_basenames is not None
                    and not any(c in only_basenames for c in candidates)):
                continue
            rows.setdefault(base_key, line)

    # A union log with NO rows is not a georeferenced merge: the workflow
    # imports it, runs -update against zero constraints, and ships an
    # UNGEOREFERENCED merged component with workflow_success true
    # (audit 2026-08-07). Refuse instead, naming what was asked for.
    if not rows:
        raise ValueError(
            f'The union flight log for {output_dir} would have ZERO rows: '
            f'{len(zone_logs)} zone log(s) under {images_root} matched none '
            f'of the '
            f'{"whole scene" if only_basenames is None else str(len(only_basenames)) + " requested image(s)"}'
            '. Importing it would leave the merged component ungeoreferenced '
            'while every step still reports success. Check that the zone '
            'logs belong to these components.')
    if only_basenames is not None and len(rows) < len(only_basenames) // 2:
        logger.error(
            'Union flight log covers only %d of %d requested image(s) - more '
            'than half the merge inputs have NO trajectory constraint',
            len(rows), len(only_basenames))

    suffix = f'_{tag}' if tag else ''
    crs_tag = 'local' if local_frame else f'{zone}{band}'
    union_path = os.path.join(output_dir, f'flight_log{suffix}_{crs_tag}_UTM.txt')
    with open(union_path, 'w', encoding='utf-8', newline='\r\n') as f:
        f.write(header + '\n' + '\n'.join(rows.values()) + '\n')

    if local_frame:
        params_path = write_flight_log_params(
            os.path.join(METADATA_DIR, 'FlightLogParamsLocal.xml'),
            os.path.join(output_dir, 'FlightLogParams_local.xml'),
            frame='local_euclidean')
    else:
        params_path = write_flight_log_params(
            os.path.join(METADATA_DIR, 'FlightLogParams.xml'),
            os.path.join(output_dir, f'FlightLogParams_{zone}{band}.xml'),
            zone, band)
    logger.info('flight log%s: %d rows -> %s', suffix, len(rows), union_path)
    return union_path, params_path


def snapshot_rs_log(dest: str, logger) -> None:
    src = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Temp', 'RealityScan.log')
    try:
        shutil.copyfile(src, dest)
    except (OSError, shutil.Error) as exc:
        logger.warning('Could not snapshot RealityScan.log: %s', exc)


def rs_finalizing_counts(rslog_path: str,
                         expected_rsaligns: list[str]) -> dict:
    """RealityScan's 'Finalizing N component' line(s) from an attempt's rslog
    snapshot, validated against a run-unique token first.

    A snapshot is only trusted when EVERY complist path appears as an
    importComponent parameter - RealityScan truncates its global log per
    launch, so a concurrent instance turns the snapshot into a splice of two
    runs (FINDINGS 2026-07-27). The count's exact semantics are NOT
    established (new components? scene total?), so callers record this as a
    cross-check and never gate on it.
    """
    out = {'valid': False, 'counts': []}
    try:
        with open(rslog_path, encoding='utf-8', errors='replace') as f:
            text = f.read()
    except OSError:
        return out
    imported = set(re.findall(r"importComponent' with parameter '([^']+)'", text))
    expected = {os.path.normcase(p) for p in expected_rsaligns}
    seen = {os.path.normcase(p) for p in imported}
    out['valid'] = expected <= seen
    out['counts'] = [int(n) for n in
                     re.findall(r'Finalizing (\d+) component', text)]
    if not out['valid']:
        out['missing'] = sorted(expected - seen)
    return out


# ----------------------------------------------------------------------
# Workflow wrappers
# ----------------------------------------------------------------------

def run_merge_workflow(cli: RealityScanCLI, complist_path: str, out_dir: str,
                       name: str, mode: str, settings: list[str],
                       flight_log: str | None, params: str | None,
                       images_root: str, logs_dir: str, harvest: bool,
                       logger, orphan_inputs=None, preserve_component_poses=False):
    """One MergeZoneComponents.bat invocation with env plumbing."""
    assert_safe_merge_harvest(images_root)
    load_project_occlusion(batch_root=images_root or None)
    for key in ('RS_MERGE_ORPHAN_LIST', 'RS_MERGE_ORPHAN_MASKS', 'RS_MERGE_ORPHAN_ROOT',
                'RS_MERGE_ORPHAN_LOG', 'RS_MERGE_ORPHAN_PARAMS', 'RS_MERGE_COMPONENT_FEATURES'):
        os.environ.pop(key, None)
    if orphan_inputs is not None:
        if mode != 'align':
            raise ValueError('orphan injection is an align-only operation')
        preserve_component_poses = True
        os.environ['RS_MERGE_COMPONENT_FEATURES'] = str(orphan_inputs['component_features'])
        if orphan_inputs['has_orphans']:
            for key, field in [('LIST', 'list'), ('MASKS', 'masks'), ('ROOT', 'root'),
                               ('LOG', 'flight_log'), ('PARAMS', 'params')]:
                os.environ['RS_MERGE_ORPHAN_' + key] = orphan_inputs[field]
    if preserve_component_poses:
        flight_log = None  # never reimport navigation for estimated component poses
    if flight_log:
        os.environ['RS_MERGE_FLIGHT_LOG'] = flight_log
        os.environ['RS_MERGE_FLIGHT_LOG_PARAMS'] = params or ''
    else:
        os.environ.pop('RS_MERGE_FLIGHT_LOG', None)
        os.environ.pop('RS_MERGE_FLIGHT_LOG_PARAMS', None)
    if harvest:
        os.environ['RS_MERGE_HARVEST'] = '1'
        os.environ['RS_MERGE_IMAGES_ROOT'] = images_root
    else:
        os.environ.pop('RS_MERGE_HARVEST', None)
        os.environ.pop('RS_MERGE_IMAGES_ROOT', None)
    args = [complist_path, out_dir, name, mode, '1'] + settings
    return cli.run_batch_script('MergeZoneComponents.bat', args, logs_dir)


def assert_safe_merge_harvest(images_root: str | None = None) -> None:
    """Pool images are source-backed; this workflow must never sweep them.

    Refuse at every Python entry point and in the batch file itself, before
    settings persistence, directory creation or any RealityScan interaction.
    Copy-layout zone trees remain the supported merge input.
    """
    pool = bool(os.environ.get('RS_ALIGN_POOL_DIR', '').strip())
    if images_root:
        marker = os.path.join(images_root, 'batch_inputs.json')
        if os.path.isfile(marker):
            with open(marker, encoding='utf-8') as fh:
                batch = json.load(fh)
            pool = pool or str(batch.get('params', {}).get(
                'batch_zone_layout', '')).lower() == 'pool'
    if pool:
        raise ValueError('REFUSING merge: source-backed pool declared by '
                         'RS_ALIGN_POOL_DIR or batch_inputs.json. '
                         'Merge XMP harvesting must not write or move its '
                         'sidecars. Use pipeline-owned copy-layout zones.')


def peel_members_from(out_dir: str, name: str, counts: list[int]) -> list[list[str]]:
    """Read and validate measured membership, paired with each peeled export.

    The existing align reader only extracts column zero without validating its
    header/count. Here independent ordinal counts must agree before adoption.
    Duplicate basenames are legitimate copy-layout cameras and are preserved.
    """
    memberships = []
    for index, count in enumerate(counts):
        path = os.path.join(out_dir, 'identity', f'{name}_c{index}.csv')
        with open(path, encoding='utf-8-sig', newline='') as fh:
            header = re.fullmatch(r'#cameras\s+(\d+)\s*', fh.readline().strip())
            if not header or int(header[1]) != count:
                raise ValueError(f'{path}: registration header disagrees with peel count {count}')
            names = []
            for row in csv.reader(fh, strict=True):
                if not row or row[0].startswith('#'):
                    continue
                if not row[0].strip():
                    raise ValueError(f'{path}: empty camera identity')
                names.append(row[0].strip())
        if len(names) != count:
            raise ValueError(f'{path}: {len(names)} camera rows, expected {count}')
        memberships.append(names)
    return memberships


def peel_counts_from(out_dir: str) -> list[int]:
    """Per-component camera counts from the workflow's identity_r<K>
    harvest dirs. The peel exports the SELECTED (maximal) component's
    sidecars each lap (-exportXMPForSelectedComponent), so identity_r<K>
    holds exactly component K's sidecars and the FILE COUNT is its
    camera count directly (stems are ordinal in merge scenes - B10 -
    so only the count carries information). Maximal-first order,
    matching the <name>_c<K>.rsalign export naming."""
    sizes = []
    k = 0
    while True:
        d = os.path.join(out_dir, f'identity_r{k}')
        if not os.path.isdir(d):
            break
        n = len([f for f in os.listdir(d) if f.lower().endswith('.xmp')])
        if n == 0:
            break
        sizes.append(n)
        k += 1

    # A TRUNCATED peel and an exhausted one look identical here - the walk
    # stops at the first missing directory either way. MergeZoneComponents.bat
    # now writes PEEL_TRUNCATED.txt when it stops on its lap ceiling instead of
    # on an empty scene, and these counts are exactly what attribute_result
    # does its camera arithmetic with. An incomplete set does not merely lose
    # components; it makes every attribution downstream wrong. Refuse rather
    # than score it. Reachable, not hypothetical: NA165/H2060 finished its
    # aligns with 43 components against the old cap of 40.
    marker = os.path.join(out_dir, 'PEEL_TRUNCATED.txt')
    if os.path.isfile(marker):
        try:
            with open(marker, encoding='utf-8', errors='replace') as fh:
                detail = fh.read().strip()
        except OSError:
            detail = '(marker unreadable)'
        raise RuntimeError(
            f'The component peel in {out_dir} hit its ceiling instead of '
            f'exhausting the scene ({detail}). The {len(sizes)} camera counts '
            'it produced are INCOMPLETE, and the fusion attribution is built '
            'on exactly those counts - scoring this attempt would silently '
            'mis-assign cameras. Raise RS_MAX_PEEL_COMPONENTS and re-run.')
    return sizes


# ----------------------------------------------------------------------
# Cluster merge loop
# ----------------------------------------------------------------------

def merge_cluster(cli: RealityScanCLI, cluster: list[dict], cluster_idx: int,
                  output_dir: str, images_root: str, ladder: list[dict],
                  min_size: int, logs_dir: str, logger,
                  merge_scope: str = 'neighbour',
                  # POLICY PROVENANCE (owner-directed analysis, 2026-08-07).
                  # The 0.0 default and the drivers' explicit 0.0025 are the
                  # TWO HALVES of one owner decision (DECISION IN FORCE,
                  # 2026-07-28, HANDOFF): "Bounded loss at 0.25% of input
                  # cameras... Default remains 0 (exact only) - the 0.25% is
                  # passed explicitly by the driver, warned at startup."
                  # Forced by the hull incident: RealityScan fused 4,860 of
                  # 4,865 cameras on every rung and exact-subset arithmetic
                  # rejected it three times - the ACCEPTANCE MATH, not the
                  # fusion, was the failure. Small loss is EVIDENCE FOR a
                  # real joint solve (weak seam cameras shed; zero loss on a
                  # zero-shared-imagery "fusion" is the co-location
                  # signature - the rigid-glue lesson). The budget stays
                  # small because large or scale-mismatched loss flags a
                  # defective fuse (the 0.175-vs-0.220 rigid fuse) and
                  # measured loss is not fully separable from harvest
                  # instrument noise (locked sidecars read as a silent -2).
                  # Library stays exact-only; every driver opts in
                  # EXPLICITLY and the choice is logged per attempt. Do not
                  # move this into rs_settings defaults - drivers inheriting
                  # another session's stored merge options is a recorded
                  # incident (final review 2026-07-29, item c).
                  loss_tolerance_frac: float = 0.0,
                  pair_gate: str = 'overlap',
                  max_scene_cameras: int = MAX_MERGE_SCENE_CAMERAS,
                  orphan_context=None) -> dict:
    """Run the escalation ladder on one border-connected cluster until
    convergence. Returns the cluster record for the report, including the
    final component list (paths + manifests) for the assembly stage."""
    assert_safe_merge_harvest(images_root)
    if orphan_context is not None and merge_scope != 'neighbour':
        raise ValueError('orphan injection requires pairwise neighbour scope')
    tag = f'cluster_{cluster_idx}'
    cdir = tempfile.mkdtemp(prefix=f'{tag}_', dir=output_dir)

    current = list(cluster)  # manifests, each with 'rsalign' on disk
    record = {'cluster': tag,
              'inputs': [component_analysis.component_key(m) for m in cluster],
              'input_cameras': sum(m['camera_count'] for m in cluster),
              'attempts': [], 'converged': False}

    if len(current) < 2:
        record['converged'] = True
        record['final_components'] = [{
            'key': component_analysis.component_key(current[0]),
            'rsalign': current[0]['rsalign'],
            'camera_count': current[0]['camera_count'],
            'members': len(current[0]['images']),
            'origin': 'single-component cluster - no merge attempted',
            'inputs': [component_analysis.component_key(current[0])],
        }]
        logger.info('%s: single component, no attempts needed', tag)
        return record

    members_union = set()
    for m in current:
        members_union |= set(m['images'])

    cluster_names = {os.path.basename(os.path.dirname(m['rsalign']))
                     for m in current}
    if orphan_context is None:
        log_path, params_path = build_union_flight_log(
            images_root, cdir, logger,
            only_basenames={b.lower() for b in members_union}, tag=tag)
    else:
        log_path, params_path = orphan_context['flight_log'], None

    attempt_no = 0
    # Growth targets, largest first (the order grow_zone also uses: a big
    # component is the best anchor to absorb a fragment into).
    #
    # In 'neighbour' scope each attempt is scoped to ONE target plus the
    # components whose bbox borders it (find_borders expands BOTH boxes by
    # DEFAULT_BORDER_MARGIN_M, so the effective gap tolerance is 20 m) - exactly
    # what find_borders' docstring says merging should be attempted between, and
    # which the pre-2026-07-27 code computed and then threw away. Observed cost
    # of throwing it away: H2024 cluster_1 put 12 components in one scene, so a
    # failure named no pair; cluster_0 ran all three rungs with a 0.236-scale
    # component in the scene every time, so we never learned whether its two
    # sound siblings would have fused alone.
    #
    # 'cluster' scope keeps the old all-at-once behaviour so the two can be
    # COMPARED rather than assumed.
    exhausted: set[str] = set()
    # Every subset already handed to the ladder. Without this a symmetric
    # pair costs SIX attempts instead of three: target A yields {A, B}, then
    # target B yields the identical set. A subset whose members are unchanged
    # has already had all three rungs run against it.
    attempted: set[frozenset] = set()
    unresolved: set[frozenset] = set()
    # Synthetic component key -> the ORIGINAL input keys behind it, resolved
    # transitively. Needed because a second-round fusion's attribution names
    # first-round synthetic keys, and the scale gate is keyed by original
    # input keys. Without this every merged component is 'unmeasured' and the
    # gate blocks the very thing the ladder produced.
    origin_map = {component_analysis.component_key(m):
                  [component_analysis.component_key(m)] for m in current}
    new_keys: set[str] = set()
    while True:
        if merge_scope == 'neighbour':
            target_key = next((k for k in growth_order(current)
                               if k not in exhausted), None)
            if target_key is None:
                break
            subset = neighbour_subset(current, target_key, logger,
                                      pair_gate=pair_gate)
            if orphan_context is not None:
                target = next(m for m in subset if component_analysis.component_key(m) == target_key)
                neighbours = [m for m in subset if component_analysis.component_key(m) != target_key
                              and frozenset((target_key, component_analysis.component_key(m))) not in attempted]
                subset = ([target, sorted(neighbours, key=component_analysis.component_key)[0]]
                          if neighbours else [target])
            if len(subset) < 2:
                logger.info('%s: %s relates to nothing else - no merge attempted',
                            tag, target_key)
                exhausted.add(target_key)
                continue
            subset_sig = frozenset(component_analysis.component_key(m)
                                   for m in subset)
            if subset_sig in attempted:
                logger.info('%s: %s resolves to a subset already attempted - '
                            'skipping (its members have not changed)',
                            tag, target_key)
                exhausted.add(target_key)
                continue
            attempted.add(subset_sig)
            logger.info('%s: growing %s against %d bordering neighbour(s)',
                        tag, target_key, len(subset) - 1)
        else:
            target_key = None
            subset = list(current)
            if len(subset) < 2:
                break
            subset_sig = frozenset(component_analysis.component_key(m)
                                   for m in subset)
            if subset_sig in attempted:
                break
            attempted.add(subset_sig)

        # Memory-envelope guard: refuse over-ceiling scenes BEFORE any RS
        # time is spent (C-20260802-01 - an over-envelope attempt burned
        # 5.6 unattended hours and then OOM'd; the next one killed the
        # driver). Refusal, not resizing: subset sizing belongs to the
        # driver's complists; the guard is the backstop.
        refuse, subset_cams = scene_ceiling_verdict(subset, max_scene_cameras)
        if refuse:
            unresolved.add(subset_sig)
            logger.warning(
                '%s: candidate subset of %d components sums to %s cameras - '
                'OVER the %s-camera merge-scene ceiling (C-20260802-01: 44k '
                'cams -> 0x8007000E at 319.5 GB commit on the 192 GB box; '
                '34k fit at 262 GB). Attempt REFUSED before launch.',
                tag, len(subset), f'{subset_cams:,}', f'{max_scene_cameras:,}')
            record['attempts'].append({
                'label': 'over_scene_ceiling', 'refused': True,
                'input_count': len(subset), 'input_cameras': subset_cams,
                'ceiling': max_scene_cameras, 'target': target_key})
            if merge_scope == 'neighbour' and target_key is not None:
                exhausted.add(target_key)
                continue
            break

        # Mechanism-aware rung selection - see effective_ladder_for. In
        # {c2, z4_c1, z4_c2} only c2-z4_c1 share imagery while z4_c2 merely
        # bbox-overlaps; a merge rung would glue all three, silently absorbing
        # an object whose relation is purely spatial. Align-only lets content
        # decide its fate (which is exactly what happened: align fused all
        # three on content, proving z4_c2 belonged).
        effective_ladder = effective_ladder_for(subset, ladder)
        if orphan_context is not None:
            effective_ladder = [step for step in effective_ladder if step['mode'] == 'align']
            if not effective_ladder:
                unresolved.add(subset_sig)
                record['attempts'].append({'refused': True, 'label': 'orphan_align_rung_required'})
                exhausted.add(target_key)
                continue
        if len(effective_ladder) != len(ladder):
            logger.info('%s: shared-image graph does not span the subset - '
                        'align-only rungs (%d of %d); a merge rung could only '
                        'rigid-glue here', tag, len(effective_ladder), len(ladder))

        rung = 0
        fused_this_target = False
        while rung < len(effective_ladder):
            step = effective_ladder[rung]
            attempt_no += 1
            adir = os.path.join(cdir, f'attempt_{attempt_no}_{step["label"]}')
            os.makedirs(adir, exist_ok=True)
            # Control inputs must not make the batch's fresh OUTPUT directory dirty.
            complist = os.path.join(cdir, f'attempt_{attempt_no}.complist')
            with open(complist, 'w', encoding='utf-8', newline='\r\n') as f:
                f.write('\n'.join(m['rsalign'] for m in subset) + '\n')

            logger.info('--- %s attempt %d: %s over %d components%s ---',
                        tag, attempt_no, step['label'], len(subset),
                        f' (target {target_key})' if target_key else '')
            t0 = time.time()
            export_name = fused_export_name(tag, attempt_no)
            orphan_evidence, orphan_inputs = None, None
            if orphan_context is not None:
                try:
                    orphan_evidence, orphan_inputs = prepare_orphan_attempt(orphan_context, subset,
                        os.path.join(cdir, f'orphan_inputs_{attempt_no}'),
                        scene_capacity=max_scene_cameras - subset_cams)
                except (OSError, ValueError, csv.Error) as exc:
                    orphan_evidence = {'refused': True, 'refusal': str(exc), 'offered_ids': [],
                        'excluded_ids': sorted(set(orphan_context['images']) - orphan_context['registered'])}
                    orphan_evidence['spatial_reasons'] = {i: 'component_support_unavailable: ' + str(exc)
                                                          for i in orphan_evidence['excluded_ids']}
                reason_counts = {}
                for identity in orphan_evidence['excluded_ids']:
                    reason = orphan_evidence['spatial_reasons'][identity]
                    reason_counts[reason] = reason_counts.get(reason, 0) + 1
                logger.info('%s attempt %d orphan scope: %d eligible, %d excluded; '
                            'excluded remain available globally; reasons: %s',
                            tag, attempt_no, len(orphan_evidence['offered_ids']),
                            len(orphan_evidence['excluded_ids']),
                            ', '.join(f'{reason}={count}' for reason, count in sorted(reason_counts.items())) or 'none')
                if orphan_evidence['refused']:
                    logger.warning('%s attempt %d orphan dispatch REFUSED: %s',
                                   tag, attempt_no, orphan_evidence['refusal'])
                    record['attempts'].append({'attempt': attempt_no, 'label': step['label'],
                                              'refused': True, 'orphans': orphan_evidence})
                    unresolved.add(subset_sig)
                    break
            result = run_merge_workflow(
                cli, complist, adir, export_name, step['mode'], step['settings'],
                log_path, params_path, images_root, logs_dir, harvest=True,
                logger=logger, **({'orphan_inputs': orphan_inputs} if orphan_context is not None else {}))
            snapshot_rs_log(os.path.join(adir, 'rslog.txt'), logger)
            registered, _r, _d = camera_registry.sanitize_and_census(images_root)

            sizes = peel_counts_from(adir)
            measured_members = None
            if result.success and sizes:
                try:
                    measured_members = peel_members_from(adir, export_name, sizes)
                except (OSError, ValueError, csv.Error) as exc:
                    logger.error('Membership census failed: %s', exc)
                    unresolved.add(subset_sig)
            if not result.success or not sizes:
                unresolved.add(subset_sig)
            # INSTRUMENT INVARIANT: an empty peel next to a non-empty export is
            # a broken instrument, not a result. Exactly this shape silently
            # discarded 5h12m of correct GPU work across two runs (the junction
            # blindness, FINDINGS 2026-07-27/28). Stop and report - never score.
            first_export = os.path.join(adir, f'{export_name}_c0.rsalign')
            if result.success and not sizes and os.path.isfile(first_export):
                raise RuntimeError(
                    f'{tag} attempt {attempt_no}: peel harvest returned EMPTY '
                    f'but {first_export} exists - the measurement channel is '
                    'broken (pose sidecars were never written or never moved). '
                    'Aborting the run instead of mis-scoring it.')
            # RealityScan's own per-op component line, recorded as a
            # cross-check. Only trusted when the snapshot provably belongs to
            # THIS attempt (every complist path present as an importComponent
            # line - rslog snapshots can be splices, FINDINGS 2026-07-27).
            # Semantics of the count are NOT established; record, never gate.
            entry_rs = rs_finalizing_counts(
                os.path.join(adir, 'rslog.txt'),
                [m['rsalign'] for m in subset])
            input_cams = sum(m['camera_count'] for m in subset)
            tol = loss_budget(input_cams, loss_tolerance_frac)
            attributed, confidence = attribute_result(subset, sizes, logger,
                                                      loss_tolerance=tol,
                                                      peel_members=measured_members,
                                                      offered_members=(orphan_evidence['offered_ids']
                                                        if orphan_evidence and measured_members is not None else None))
            adopted = [r for r in attributed if r['inputs']]
            residuals = [r for r in attributed if r['residual']]
            adopted_cams = sum(r['camera_count'] for r in adopted)
            # Duplicate copies RealityScan folded into one camera are not
            # lost cameras (attribute_result, 2026-09-06): the count deficit
            # they leave is provenance, and only the remainder is a loss.
            retention_measured = (measured_members is not None and
                                  confidence == 'exact')
            collapsed = (sum(r['collapsed'] for r in adopted)
                         if retention_measured else None)
            lost = (sum(r['loss'] for r in adopted)
                    if adopted and retention_measured else None)
            if confidence != 'exact':
                unresolved.add(subset_sig)

            entry = {'attempt': attempt_no, 'label': step['label'],
                     'mode': step['mode'], 'workflow_success': result.success,
                     'errors': result.errors, 'census_leftover': registered,
                     'peel_sizes': sizes, 'attribution': confidence,
                     'scope': merge_scope, 'target': target_key,
                     'input_count': len(subset), 'adopted_count': len(adopted),
                     'residual_count': len(residuals),
                     'camera_delta': (adopted_cams - input_cams) if adopted else None,
                     'membership_evidence': ('registration' if measured_members is not None
                                             else 'unmeasured'),
                     'duplicates_collapsed': collapsed if adopted else None,
                     'cameras_lost': lost,
                     'loss_tolerance': tol,
                     'loss_tolerance_frac': loss_tolerance_frac,
                     'rs_finalizing': entry_rs,
                     'duration_s': round(time.time() - t0, 1)}
            record['attempts'].append(entry)
            if orphan_evidence is not None:
                entry['orphans'] = orphan_evidence

            fused = any(len(r['inputs']) >= 2 for r in adopted)
            # Bounded loss, not never-shrink - the pure decision lives in
            # acceptance_verdict so the suite drives the real thing.
            accept, rejection = acceptance_verdict(
                result.success, len(adopted), fused, confidence, lost, tol)
            if rejection:
                entry['rejected'] = rejection
            if rejection == 'shrink':
                logger.warning('%s attempt %d SHRANK by %d cameras, over the '
                               '%d-camera budget (%.2f%%) - rejected',
                               tag, attempt_no, lost, tol,
                               100.0 * loss_tolerance_frac)
            elif rejection == 'ambiguous_attribution':
                logger.warning('%s attempt %d fused but attribution is %s - '
                               'rejected (membership would be untrustworthy)',
                               tag, attempt_no, confidence)
            elif accept and lost:
                logger.info('%s attempt %d accepted with a %d-camera loss '
                            '(budget %d, %.2f%% of %d input cameras)',
                            tag, attempt_no, lost, tol,
                            100.0 * loss_tolerance_frac, input_cams)
            if accept:
                new_subset = []
                for res in adopted:
                    rsalign = os.path.join(
                        adir, f'{export_name}_c{res["peel_index"]}.rsalign')
                    if not os.path.isfile(rsalign):
                        logger.warning('expected export missing: %s', rsalign)
                        continue
                    # Matches the exported file stem exactly (see export_name).
                    # peel_index restarts at 0 every attempt, so without the
                    # attempt number two accepted fusions in one cluster both
                    # claimed `<tag>_m_c0`: find_borders' _validate raised
                    # "duplicate component identity" and killed the run (H2024
                    # 2026-07-28, cluster_1 attempts 1 and 5), and the second
                    # silently clobbered the first's origin_map entry, losing
                    # the scale-gate lineage.
                    comp_name = f'{export_name}_c{res["peel_index"]}'
                    manifest = component_manifest.build_manifest(
                        zone=tag, component=comp_name, rsalign_path=rsalign,
                        images=res['members'] or [],
                        bbox_utm=component_manifest.bbox_from_flight_log(
                            log_path, res['members'] or []),
                        event='cluster_merge_attribution')
                    manifest['camera_count'] = res['camera_count']
                    manifest['attribution'] = {'inputs': res['inputs'],
                                               'confidence': confidence}
                    component_manifest.write_manifest(manifest)
                    new_subset.append(manifest)
                if len(new_subset) == len(adopted):
                    # Splice the results back IN PLACE of the subset, leaving the
                    # rest of the cluster untouched. The fused manifest carries a
                    # freshly computed bbox, so the next round's neighbour
                    # selection sees the grown extent.
                    subset_keys = {component_analysis.component_key(m)
                                   for m in subset}
                    # Resolve each result back to ORIGINAL input keys, through
                    # any earlier fusion, so the scale gate can find verdicts.
                    new_keys = set()
                    for nm in new_subset:
                        nk = component_analysis.component_key(nm)
                        new_keys.add(nk)
                        srcs = (nm.get('attribution') or {}).get('inputs') or []
                        origins = []
                        for s in srcs:
                            origins.extend(origin_map.get(s, [s]))
                        origin_map[nk] = sorted(set(origins)) or [nk]
                    current = [m for m in current
                               if component_analysis.component_key(m)
                               not in subset_keys] + new_subset
                    if orphan_context is not None:
                        orphan_context['registered'].update(_orphan_id(i) for m in new_subset for i in m['images'])
                    entry['accepted'] = True
                    unresolved.discard(subset_sig)
                    fused_this_target = True
                    logger.info('%s: fused %d -> %d; cluster now %d component(s)',
                                tag, len(subset), len(new_subset), len(current))
                    break
                logger.warning('%s: exports incomplete (%d of %d) - treating '
                               'attempt as failed', tag, len(new_subset),
                               len(adopted))
                unresolved.add(subset_sig)
            rung += 1

        if fused_this_target:
            # Reopen ONLY the targets that border a newly created component.
            # Clearing everything was quadratic: a target whose neighbour set
            # did not change has already had all three rungs run against it,
            # and the attempted-subset memo would skip it anyway.
            touching = set()
            for entry in component_analysis.find_borders(current):
                a, b = entry['pair']
                if a in new_keys:
                    touching.add(b)
                if b in new_keys:
                    touching.add(a)
            exhausted -= (touching | new_keys)
            if len(current) < 2:
                break
            continue
        if merge_scope == 'neighbour':
            if orphan_context is None:
                exhausted.add(target_key)
            continue
        break

    current_keys = {component_analysis.component_key(m) for m in current}
    record['unresolved_subsets'] = [sorted(s) for s in sorted(
        unresolved, key=lambda s: sorted(s)) if s <= current_keys]
    record['converged'] = not record['unresolved_subsets']
    record['final_components'] = [{
        'key': component_analysis.component_key(m),
        'rsalign': m['rsalign'],
        'camera_count': m['camera_count'],
        'members': len(m.get('images') or []),
        'origin': ('fused' if m.get('attribution') else 'unfused input'),
        # ORIGINAL input keys behind this component. The scale gate is keyed
        # by them; without this a merged component looked 'unmeasured' and was
        # blocked from modelling regardless of its real scale.
        'inputs': origin_map.get(component_analysis.component_key(m),
                                 [component_analysis.component_key(m)]),
    } for m in current]
    logger.info('%s %s: %d final component(s)', tag,
                'converged' if record['converged'] else 'INCOMPLETE', len(current))
    return record


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def component_identity(component: dict) -> dict:
    """Content and provenance at the original export location, never mtime alone."""
    path = component['rsalign']
    identity = align_fingerprint.file_identity(path)
    if identity is None or not identity['bytes']:
        raise FileNotFoundError(f'component identity unavailable: {path}')
    declared = dict(component)
    if 'images' in declared:
        declared['images'] = sorted(declared['images'])
    return {
        'component': identity,
        'manifest': align_fingerprint.file_identity(path + '.manifest.json'),
        'registration': align_fingerprint.file_identity(os.path.join(
            os.path.dirname(path), 'identity',
            os.path.splitext(os.path.basename(path))[0] + '.csv')),
        'alignment': align_fingerprint.file_identity(os.path.join(
            os.path.dirname(path), align_fingerprint.FINGERPRINT_NAME)),
        'declared_sha256': hashlib.sha256(json.dumps(
            declared, sort_keys=True, allow_nan=False).encode('utf-8')).hexdigest(),
    }


def run_fingerprint(input_keys, ladder_name, merge_scope, pair_gate,
                    loss_tolerance_frac, min_size, assemble_only, *,
                    input_manifests=None, images_root=None,
                    max_scene_cameras=MAX_MERGE_SCENE_CAMERAS, orphan_context=None) -> dict:
    """Everything that changes what a cluster's result MEANS.

    Resume is only sound when the new run would have asked the same question.
    The input SET matters (a different set repartitions the clusters), as do
    the ladder, the scope and the pair gate; loss_tolerance matters because it
    changes what counts as an acceptable fusion, which is an acceptance
    semantic on the deliverable itself. Order is deliberately ignored -
    sorted() - because input order does not affect partitioning.
    """
    identities = None
    if input_manifests is not None:
        manifests = sorted(input_manifests, key=component_analysis.component_key)
        if sorted(input_keys) != [component_analysis.component_key(m) for m in manifests]:
            raise ValueError('fingerprint keys do not match input manifests')
        identities = [component_identity(m) for m in manifests]
    provenance = []
    if images_root:
        for root, _dirs, files in os.walk(images_root):
            for name in sorted(files):
                if (name == 'batch_inputs.json' or name.endswith('.imagelist')
                        or (name.startswith('flight_log') and name.endswith('.txt'))):
                    path = os.path.join(root, name)
                    identity = align_fingerprint.file_identity(path)
                    if identity is None:
                        raise FileNotFoundError(f'navigation identity unavailable: {path}')
                    provenance.append(identity)
    recipe_paths = [__file__, os.path.join(os.path.dirname(__file__), 'calibration.xml'),
                    os.path.join(os.path.dirname(METADATA_DIR),
                                         'Scripts', 'MergeZoneComponents.bat')]
    recipe_paths.extend(os.path.join(METADATA_DIR, name) for name in (
        'RegistrationExportParams.xml', 'XMPExportParams.xml',
        'FlightLogParams.xml', 'FlightLogParamsLocal.xml'))
    return {
        'schema': 3,
        'inputs': sorted(input_keys),
        'input_identities': identities,
        'navigation': sorted(provenance, key=lambda p: p['path']),
        'recipe': [align_fingerprint.file_identity(p) for p in recipe_paths],
        'max_scene_cameras': max_scene_cameras,
        'orphans': orphan_context['fingerprint'] if orphan_context is not None else None,
        'ladder': ladder_name,
        'merge_scope': merge_scope,
        'pair_gate': pair_gate,
        'loss_tolerance': loss_tolerance_frac,
        'min_size': min_size,
        'assemble_only': bool(assemble_only),
    }


def load_resumable_clusters(output_dir, fingerprint, logger) -> dict:
    """Converged clusters from a prior report, keyed by their input set.

    Refuses rather than guesses. A prior report written by a DIFFERENT
    question (other ladder, other gate, other inputs) is not resumable, and
    saying so loudly beats silently blending two runs' semantics into one
    deliverable.

    Also verifies every carried component file still EXISTS: a record whose
    .rsalign was moved or cleaned away would otherwise sail through into the
    assembly complist and fail there, hours later.
    """
    path = os.path.join(output_dir, 'merge_report.json')
    if not os.path.isfile(path):
        return {}
    if fingerprint.get('schema') != 3 or not fingerprint.get('input_identities'):
        logger.warning('--resume: content-backed input identities required')
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            prior = json.load(f)
    except (OSError, ValueError) as exc:
        logger.warning('--resume: could not read %s (%s) - starting fresh',
                       path, exc)
        return {}

    if not isinstance(prior, dict):
        logger.warning('--resume: report is not an object - starting fresh')
        return {}
    prior_fp = prior.get('run_fingerprint')
    if not isinstance(prior_fp, dict):
        logger.warning(
            '--resume: %s predates run fingerprints, so it cannot be shown to '
            'describe the same question - starting fresh. This run writes a '
            'fingerprint, so a future restart WILL be resumable.', path)
        return {}
    if prior_fp != fingerprint:
        differing = sorted(k for k in set(prior_fp) | set(fingerprint)
                           if prior_fp.get(k) != fingerprint.get(k))
        logger.warning('--resume: prior report describes a DIFFERENT run '
                       '(differs on: %s) - starting fresh, nothing reused',
                       ', '.join(differing) or 'unknown')
        return {}

    out, skipped = {}, 0
    for rec in prior.get('clusters') or []:
        if not isinstance(rec, dict) or not rec.get('converged'):
            skipped += 1
            continue
        if rec.get('unresolved_subsets') or not rec.get('final_components'):
            skipped += 1
            continue
        missing = [c.get('rsalign') for c in rec.get('final_components') or []
                   if not (c.get('rsalign') and os.path.isfile(c['rsalign']))]
        if missing:
            logger.warning('--resume: %s converged previously but %d of its '
                           'component file(s) are gone - re-merging it',
                           rec.get('cluster'), len(missing))
            skipped += 1
            continue
        try:
            identities = [component_identity(c) for c in rec['final_components']]
        except (OSError, ValueError, KeyError):
            skipped += 1
            continue
        if rec.get('final_identities') != identities:
            logger.warning('--resume: %s output content/provenance changed or unrecorded',
                           rec.get('cluster'))
            skipped += 1
            continue
        key = frozenset(rec.get('inputs') or [])
        if key:
            out[key] = rec
    logger.info('--resume: %d converged cluster(s) reusable from %s%s',
                len(out), path,
                (', %d not reusable (unconverged or missing files)' % skipped)
                if skipped else '')
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger('merge_zones')
    if sys.argv[1:] == ['--validate_project_occlusion']:
        try:
            if load_project_occlusion() is None:
                raise ValueError('Native occlusion validation requires RS_SELECTION_MANIFEST')
            return 0
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.error('Project occlusion refused: %s', exc)
            return 1
    try:
        assert_safe_merge_harvest()
    except ValueError as exc:
        logger.error('%s', exc)
        return 1
    settings = SettingsStore()

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--components_root', help='aligned_components directory')
    parser.add_argument('--images_root', help='batched_images_by_zone directory')
    parser.add_argument('--output', help='merge output directory')
    parser.add_argument('--name', default=None, help='assembly project name (default Merged)')
    parser.add_argument('--max_scene_cameras', type=int,
                        default=MAX_MERGE_SCENE_CAMERAS,
                        help='pre-launch refusal ceiling on merge-scene '
                             'camera count (default %(default)s; '
                             'C-20260802-01: 44k cams OOMed at 319.5 GB '
                             'commit on the 192 GB box, 34k fit). Plain '
                             'argparse default by design - safety limits '
                             'never inherit from rs_settings.')
    parser.add_argument('--min_size', type=int, default=None,
                        help='report floor: components below this are flagged as pockets (default 50)')
    parser.add_argument('--target', type=float, default=None,
                        help='INFORMATIONAL ONLY: fraction reported against, never a gate')
    parser.add_argument('--project_label', default=None,
                        help='expedition_dive label for RC_projects daily saves')
    parser.add_argument('--complist', default=None,
                        help='optional explicit .rsalign list (grow->merge handoff)')
    parser.add_argument('--visible', default=None,
                        help='true = GUI-visible RealityScan instances (RS_HEADLESS=0)')
    parser.add_argument('--auto_model', default=None,
                        help='true = run GenerateModel per surviving component '
                             '>= min_size. DEPRECATED (2026-08-07): prefer '
                             'run_models.py --workspace, which adds '
                             'smallest-first ordering, resumability and the '
                             'quantile-ratio scale fallback for fused '
                             'components; kept for compatibility')
    parser.add_argument('--ladder', default=None,
                        help='merge_first (default) or content_first - see LADDERS')
    parser.add_argument('--loss_tolerance', default=None,
                        help='fraction of input cameras a fusion may drop and '
                             'still be accepted (e.g. 0.0025 = 0.25%%). '
                             'Default 0 = exact subset sums only. Owner '
                             'decision: it changes acceptance semantics on the '
                             'deliverable, so it is never a silent default.')
    parser.add_argument('--merge_scope', default=None,
                        help='neighbour (default) = grow one component at a time against only its bbox neighbours; cluster = the old all-at-once behaviour, kept for comparison')
    parser.add_argument('--pair_gate', default=None,
                        help='overlap (default) = components relate only when '
                             'they share imagery or their bboxes truly overlap '
                             '(owner uniqueness criterion 2026-07-28); border = '
                             'the old 10 m-margin adjacency, kept for comparison')
    parser.add_argument('--assemble_only', default=None,
                        help='true = skip the merge ladder entirely; collect '
                             'every input component into ONE georeferenced '
                             'project and stop (hull-import staging)')
    parser.add_argument('--resume', default=None,
                        help='true (default) = reuse CONVERGED clusters from an '
                             'existing merge_report.json in --output and merge '
                             'only what is left. false = start fresh, ignoring '
                             'any prior report')
    parser.add_argument('--scale_gate', default=None,
                        help='true (default) = refuse to MODEL a component whose '
                             'metric scale is out of band or unmeasurable')
    parser.add_argument('--scale_min', type=float, default=None,
                        help=f'lower scale bound (default {scale_oracle.DEFAULT_SCALE_MIN})')
    parser.add_argument('--scale_max', type=float, default=None,
                        help=f'upper scale bound (default {scale_oracle.DEFAULT_SCALE_MAX})')
    parser.add_argument('--orphan_policy', default=None,
                        help='Explicit pair-local orphan policy JSON; absent preserves legacy component-only merging')
    parser.add_argument('--orphan_policy_sha256', default=None,
                        help='Planner pin for the exact approved orphan policy bytes')
    parser.add_argument('--orphan_selection_manifest', default=None,
                        help='Approved project selection JSON; defaults to RS_SELECTION_MANIFEST only when orphan_policy is supplied')
    args = parser.parse_args()
    try:
        if args.orphan_policy_sha256 and not args.orphan_policy:
            raise ValueError('orphan_policy_sha256 requires orphan_policy')
        if args.orphan_policy:
            read_orphan_policy(args.orphan_policy, expected_sha256=args.orphan_policy_sha256)
        assert_safe_merge_harvest(args.images_root)
    except (OSError, ValueError) as exc:
        logger.error('%s', exc)
        return 1

    def ask(key, cli_value, fallback):
        # Promoted shared helper: unattended-safe prompt-with-default
        # (module_base.settings_store.SettingsStore.ask).
        return settings.ask('merge', key, cli_value, fallback)

    def truthy(v):
        return str(v).strip().lower() in ('1', 'true', 'yes', 'y')

    components_root = ask('components_root', args.components_root, '')
    images_root = ask('images_root', args.images_root, '')
    output_dir = ask('output', args.output, '')
    merged_name = ask('name', args.name, 'Merged')
    min_size = int(ask('min_size', args.min_size, 50))
    target = float(ask('target', args.target, 0.9))
    project_label = ask('project_label', args.project_label, '')
    # --visible's DEFAULT routes through the shared machine-constant
    # resolution (module_base.settings_store.realityscan_env - the single
    # RS_HEADLESS source of truth; headless defaults False = visible,
    # owner decision 2026-08-07, and an RS_HEADLESS already in the
    # environment seeds the default too). The CLI flag / stored merge
    # answer stay the explicit per-run override.
    rs_env = realityscan_env(settings)
    if args.visible is None and 'RS_HEADLESS' in os.environ:
        # An EXPLICIT env var wins outright over any stored answer - a
        # previous session's persisted visible=true silently overriding
        # RS_HEADLESS=1 on an unattended run is exactly the recorded
        # "inherited another session's stored options" incident class
        # (final review 2026-07-29 item c; clean-sweep 2026-08-07).
        visible = os.environ['RS_HEADLESS'] == '0'
    else:
        visible = truthy(ask('visible', args.visible,
                             'true' if rs_env['RS_HEADLESS'] == '0' else 'false'))
    auto_model = truthy(ask('auto_model', args.auto_model, 'false'))
    if auto_model:
        # Deprecation notice only - behaviour is deliberately unchanged.
        logger.warning(
            'DEPRECATED: --auto_model is kept for compatibility only. '
            'Prefer run_models.py --workspace <root> (smallest-first, '
            'resumable, quantile-ratio scale fallback) or run_models.py '
            '--project <assembly.rsproj> --component <name> for a single '
            'component.')
    ladder_name = ask('ladder', args.ladder, 'merge_first')
    ladder = LADDERS.get(ladder_name, LADDERS['merge_first'])
    merge_scope = ask('merge_scope', args.merge_scope, 'neighbour')
    if merge_scope not in ('neighbour', 'cluster'):
        logger.error('--merge_scope must be neighbour or cluster, got %r', merge_scope)
        return 1
    pair_gate = ask('pair_gate', args.pair_gate, 'overlap')
    if pair_gate not in ('overlap', 'border'):
        logger.error('--pair_gate must be overlap or border, got %r', pair_gate)
        return 1
    assemble_only = truthy(ask('assemble_only', args.assemble_only, 'false'))
    resume = truthy(ask('resume', args.resume, 'true'))
    loss_tolerance_frac = float(ask('loss_tolerance', args.loss_tolerance, 0.0))
    if not 0.0 <= loss_tolerance_frac < 1.0:
        logger.error('--loss_tolerance must be a fraction in [0, 1), got %r',
                     loss_tolerance_frac)
        return 1
    if loss_tolerance_frac:
        logger.warning('BOUNDED LOSS ENABLED: a fusion may drop up to %.3f%% of '
                       'its input cameras and still be accepted. Every accepted '
                       'loss is recorded per attempt and in EVALUATION_READY.',
                       100.0 * loss_tolerance_frac)
    scale_gate = truthy(ask('scale_gate', args.scale_gate, 'true'))
    scale_min = float(ask('scale_min', args.scale_min, scale_oracle.DEFAULT_SCALE_MIN))
    scale_max = float(ask('scale_max', args.scale_max, scale_oracle.DEFAULT_SCALE_MAX))

    # Export the resolved answer explicitly - the .bat-side headless
    # fallback in SetVariables.bat only governs hand-run scripts. The
    # other machine constants (RS_INSTANCE / RS_CACHE_DIR) come from the
    # same resolution; values already in the environment pass through
    # unchanged.
    os.environ.update(rs_env)
    os.environ['RS_HEADLESS'] = '0' if visible else '1'
    logger.info('RealityScan instances will be %s (RS_HEADLESS=%s)',
                'GUI-visible' if visible else 'headless',
                os.environ['RS_HEADLESS'])

    if project_label:
        projects_dir = set_project_save_env(images_root, project_label)
        logger.info('Daily project saves: %s', projects_dir)

    os.makedirs(output_dir, exist_ok=True)
    logs_dir = os.path.join(output_dir, 'logs')

    # Harvest preflight: every attempt in the cluster loop peels its result
    # through a PowerShell `Get-ChildItem -Recurse` over images_root, which
    # cannot cross a directory junction - an empty peel is indistinguishable
    # from a legitimately empty scene. Refuse up front, before any GPU hours.
    try:
        assert_harvestable(images_root, logger)
    except RuntimeError as exc:
        logger.error('%s The peel harvest cannot cross a directory junction '
                     '- FINDINGS.md "The peel harvest cannot cross a '
                     'directory junction (2026-07-27)".', exc)
        return 1

    try:
        inputs = load_inputs(components_root, args.complist, logger)
    except (ValueError, FileNotFoundError) as exc:
        logger.error('%s', exc)
        return 1
    if not inputs:
        logger.error('No manifested components under %s', components_root)
        return 1
    orphan_context = None
    if args.orphan_policy:
        try:
            selection_path = args.orphan_selection_manifest or os.environ.get('RS_SELECTION_MANIFEST')
            if not selection_path or merge_scope != 'neighbour':
                raise ValueError('orphan_policy requires a selection manifest and neighbour scope')
            orphan_context = load_orphan_context(selection_path, args.orphan_policy, inputs,
                expected_policy_sha256=args.orphan_policy_sha256)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.error('Orphan preflight refused: %s', exc)
            return 1

    # Metric scale FIRST, before any ladder spends GPU hours: a component
    # that is metrically broken is not worth merging or modelling, and this is
    # the check that a camera-counting gate cannot make. An H2024 component
    # solved at 0.236 passed every other check and reached a deliverable.
    try:
        gate_log, _gate_params = build_union_flight_log(
            images_root, output_dir, logger, tag='scalegate')
        input_scales = measure_input_scales(inputs, gate_log, logger,
                                            scale_min=scale_min,
                                            scale_max=scale_max)
    except (OSError, ValueError) as exc:
        logger.warning('Could not measure input scale (%s); the model gate will '
                       'treat every component as UNMEASURED', exc)
        input_scales = {}

    if assemble_only:
        # Carried AS-IS means as-is: no twin-drop, no relatedness gating -
        # every input the operator listed reaches the assembly. Routing
        # assemble_only through partition_clusters silently discarded
        # containment twins from a hand-built complist (final review).
        clusters, plan = [[m] for m in inputs], {}
    else:
        clusters, plan = partition_clusters(inputs, logger, pair_gate=pair_gate)
    total_images = count_unique_images(images_root)

    cli = RealityScanCLI(logger)
    report = {'schema': 2,
              'input_scales': input_scales,
              'scale_gate': {'enabled': scale_gate, 'min': scale_min,
                             'max': scale_max},
              'inputs': [component_analysis.component_key(m) for m in inputs],
              'unique_images': total_images,
              'informational_target': target,
              'ladder': ladder_name,
              'twin_plan': {'discards': plan.get('discards', []),
                            'twin_resolutions': plan.get('twin_resolutions', [])},
              'assembly': {'workflow_success': False},
              'clusters': []}

    report['run_fingerprint'] = run_fingerprint(
        report['inputs'], ladder_name, merge_scope, pair_gate,
        loss_tolerance_frac, min_size, assemble_only,
        input_manifests=inputs, images_root=images_root,
        max_scene_cameras=args.max_scene_cameras, orphan_context=orphan_context)

    def flush():
        with open(os.path.join(output_dir, 'merge_report.json'), 'w',
                  encoding='utf-8') as f:
            json.dump(report, f, indent=2)

    # Reuse converged clusters from a previous run of the SAME ladder over the
    # SAME inputs. A cross-zone merge costs hours per cluster - NA165/H2063
    # lost a 12 h run to a harness restart with three clusters already
    # converged - and each converged cluster is a finished, self-contained
    # result already on disk. Only CONVERGED clusters are reused; one that was
    # mid-ladder when the run died is redone from its inputs.
    resumable = {}
    if resume:
        resumable = load_resumable_clusters(
            output_dir, report['run_fingerprint'], logger)

    for i, cluster in enumerate(clusters):
        # Match on the INPUT SET, never the cluster index: partition_clusters
        # numbers clusters by iteration order, so a changed input list would
        # silently pair one cluster's record with another cluster's work.
        prior = resumable.get(
            frozenset(component_analysis.component_key(m) for m in cluster))
        if prior is not None:
            logger.info('cluster_%d: RESUMED from a previous run - %d input(s) '
                        'already converged to %d component(s), not re-merged',
                        i, len(prior.get('inputs') or []),
                        len(prior.get('final_components') or []))
            prior = dict(prior)
            prior['cluster'] = 'cluster_%d' % i
            prior['resumed'] = True
            report['clusters'].append(prior)
            flush()
            continue
        if assemble_only:
            # Owner-directed staging (2026-07-28): the inputs are already at
            # their maximum - collect, georeference, save. No ladder. Every
            # input is carried to the assembly untouched.
            record = {
                'cluster': f'cluster_{i}',
                'inputs': [component_analysis.component_key(m) for m in cluster],
                'input_cameras': sum(m['camera_count'] for m in cluster),
                'attempts': [], 'converged': True,
                'final_components': [{
                    'key': component_analysis.component_key(m),
                    'rsalign': m['rsalign'],
                    'camera_count': m['camera_count'],
                    'members': len(m.get('images') or []),
                    'origin': 'assemble_only - carried as-is',
                    'inputs': ((m.get('attribution') or {}).get('inputs')
                               or [component_analysis.component_key(m)]),
                } for m in cluster],
            }
            logger.info('cluster_%d: assemble_only - %d component(s) carried '
                        'as-is', i, len(cluster))
        else:
            record = merge_cluster(cli, cluster, i, output_dir, images_root,
                                   ladder, min_size, logs_dir, logger,
                                   merge_scope=merge_scope,
                                   loss_tolerance_frac=loss_tolerance_frac,
                                   pair_gate=pair_gate,
                                   max_scene_cameras=args.max_scene_cameras,
                                   **({'orphan_context': orphan_context} if orphan_context is not None else {}))
        record['final_identities'] = [component_identity(c)
                                      for c in record['final_components']]
        if orphan_context is not None:
            for final in record['final_components']:
                manifest = component_manifest.load_manifest(final['rsalign'])
                orphan_context['registered'].update(measured_component_ids(manifest))
        report['clusters'].append(record)
        flush()

    if any(not c.get('converged') for c in report['clusters']):
        report['evaluation_blocked'] = 'merge attempts failed, were refused or lack membership evidence'
        flush()
        logger.error('Merge incomplete: %s. Assembly was not launched.',
                     report['evaluation_blocked'])
        return 1

    # ------------------------------------------------------------------
    # Assembly: ONE project holding every surviving component.
    # ------------------------------------------------------------------
    finals = [c for rec in report['clusters'] for c in rec['final_components']]
    logger.info('Assembly: %d surviving components across %d clusters',
                len(finals), len(clusters))
    assembly_dir = os.path.join(output_dir, 'assembly')
    os.makedirs(assembly_dir, exist_ok=True)
    complist = os.path.join(assembly_dir, 'assembly.complist')
    with open(complist, 'w', encoding='utf-8', newline='\r\n') as f:
        f.write('\n'.join(c['rsalign'] for c in finals) + '\n')
    union_log, union_params = build_union_flight_log(
        images_root, assembly_dir, logger)

    result = run_merge_workflow(
        cli, complist, assembly_dir, merged_name, 'assemble', [],
        union_log, union_params, images_root, logs_dir, harvest=False,
        logger=logger, **({'preserve_component_poses': True} if orphan_context is not None else {}))
    snapshot_rs_log(os.path.join(assembly_dir, 'rslog.txt'), logger)
    # Sidecar hygiene only. Assemble mode exports NO XMPs (it imports
    # components and georeferences them), so a sidecar scan here cannot
    # observe the assembly - it reads leftovers from whatever ran last,
    # and reported 0 for a sound 4,496-camera assembly on 2026-07-25.
    # The assembly's camera count is the manifest sum, tagged as such.
    camera_registry.sanitize_and_census(images_root)

    report['assembly'] = {
        'workflow_success': result.success,
        'errors': result.errors,
        'project': os.path.join(assembly_dir, f'{merged_name}.rsproj'),
        'cameras_from_manifests': sum(c['camera_count'] or 0 for c in finals),
    }
    flush()

    # ------------------------------------------------------------------
    # EVALUATION READY report
    # ------------------------------------------------------------------
    lines = ['EVALUATION READY - cross-zone merge terminal state',
             f'project: {report["assembly"]["project"]}',
             f'unique images across zones: {total_images}', '']
    total_registered = 0
    for rec in report['clusters']:
        lines.append(f'{rec["cluster"]}: inputs={len(rec["inputs"])} '
                     f'({rec["input_cameras"]} cams) -> '
                     f'{len(rec["final_components"])} final component(s)')
        for c in rec['final_components']:
            total_registered += c['camera_count'] or 0
            flag = ' [POCKET <min_size]' if (c['camera_count'] or 0) < min_size else ''
            lines.append(f'  - {c["key"]}: {c["camera_count"]} cams '
                         f'({c["origin"]}){flag}')
    accepted_losses = [(rec['cluster'], a['attempt'], a.get('cameras_lost'),
                        a.get('loss_tolerance'))
                       for rec in report['clusters']
                       for a in rec.get('attempts', [])
                       if a.get('accepted') and a.get('cameras_lost')]
    if loss_tolerance_frac:
        lines += ['',
                  f'BOUNDED LOSS was enabled at {100.0 * loss_tolerance_frac:.3f}% '
                  f'of input cameras.']
        if accepted_losses:
            for cluster, attempt, lost, tol in accepted_losses:
                lines.append(f'  - {cluster} attempt {attempt}: accepted a '
                             f'{lost}-camera loss (budget {tol})')
            lines.append(f'  TOTAL cameras dropped by accepted fusions: '
                         f'{sum(l for _c, _a, l, _t in accepted_losses)}')
        else:
            lines.append('  - no accepted fusion lost a camera.')

    lines += ['',
              f'total cameras across components: {total_registered} '
              f'({100.0 * total_registered / max(total_images, 1):.1f}% of unique '
              f'images; informational target was {target:.0%})',
              'Multi-component outcomes are CORRECT for multi-feature dives '
              '(bow/hull). Evaluate each component in the GUI before models.',
              '',
              '', 'METRIC SCALE (testing/scale_oracle.py, band '
              f'{scale_min:.2f}-{scale_max:.2f}, gate '
              f'{"ON" if scale_gate else "OFF"}):']
    if input_scales:
        for key, v in sorted(input_scales.items()):
            lines.append(f'  - {key}: {v["status"].upper()} - {v["explanation"]}')
    else:
        lines.append('  - not measured')
    lines += ['',
              'CAMERA COUNTS ARE THE MANIFEST SUM (the inputs). Assemble '
              'mode exports no XMPs, so nothing here observes the assembled '
              'project itself - in particular its METRIC SCALE is unmeasured, '
              'and -update is a similarity fit that can set it. Run '
              'testing/scale_oracle.py on the input components for the '
              'pre-assembly figure; measuring the deliverable needs a pose '
              'export from a COPY of the saved project.']
    # The gate file is a TERMINAL-STATE document naming a project the
    # census then reads as "merge done". Writing it before checking the
    # assembly workflow's result declared that state for a project that
    # was never saved (audit 2026-08-07): gate the write on success, and
    # on failure leave an equally loud EVALUATION_BLOCKED.txt instead.
    if not result.success:
        blocked_path = os.path.join(output_dir, 'EVALUATION_BLOCKED.txt')
        blocked = ['EVALUATION BLOCKED - the assembly workflow FAILED',
                   f'project (NOT saved): {report["assembly"]["project"]}',
                   f'errors: {result.errors or "<none reported>"}',
                   f'assembly dir: {assembly_dir}',
                   f'workflow log: {result.log_path}',
                   '',
                   'No EVALUATION_READY gate was written, so the workspace '
                   'census will not report this merge as done.',
                   ''] + lines[2:]
        with open(blocked_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(blocked) + '\n')
        report['evaluation_blocked'] = blocked_path
        flush()
        logger.error('Assembly workflow failed - see %s and %s',
                     assembly_dir, blocked_path)
        return 1

    eval_path = os.path.join(output_dir, 'EVALUATION_READY.txt')
    with open(eval_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    logger.info('\n%s', '\n'.join(lines))
    report['evaluation_ready'] = eval_path
    flush()

    if auto_model:
        model_targets = [c for c in finals if (c['camera_count'] or 0) >= min_size]
        if scale_gate:
            model_targets, blocked = apply_scale_gate(
                model_targets, input_scales, scale_min, scale_max, logger)
            report['scale_gate']['blocked'] = blocked
            flush()
        logger.info('auto_model: generating models for %d component(s)',
                    len(model_targets))
        proj = report['assembly']['project']
        model_failures = []
        for c in model_targets:
            comp_name = os.path.splitext(os.path.basename(c['rsalign']))[0]
            res = cli.run_batch_script('GenerateModel.bat',
                                       [proj, comp_name], logs_dir)
            # Snapshot per component, ALWAYS. RealityScan overwrites
            # Temp\RealityScan.log when the next instance starts, and the
            # next component starts seconds later - so a crash here leaves
            # no authoritative log at all unless it is copied now. Learned
            # from the 2026-07-26 hull crash, whose log was overwritten
            # three seconds after the minidump was written.
            rslog = os.path.join(logs_dir, f'rslog_model_{comp_name}.txt')
            snapshot_rs_log(rslog, logger)
            if not res.success:
                model_failures.append(comp_name)
                logger.error('Model workflow FAILED for %s - RealityScan log '
                             'snapshot: %s', comp_name, rslog)
            report.setdefault('models', []).append(
                {'component': comp_name, 'success': res.success,
                 'errors': res.errors, 'rslog': rslog})
            flush()

        # run_models.py stops on the first model failure "so evidence
        # survives"; this loop logged every failure and still fell through
        # to 'Merge stage complete' / return 0, so a run in which NO model
        # was produced reported success (audit 2026-08-07). Same contract
        # in both callers of GenerateModel.bat now: an aggregate check.
        logger.info('auto_model: %d of %d model(s) succeeded',
                    len(model_targets) - len(model_failures),
                    len(model_targets))
        if model_failures:
            logger.error('auto_model: %d model(s) FAILED (%s). The merge '
                         'itself succeeded - its gate is %s - but the models '
                         'are incomplete.', len(model_failures),
                         ', '.join(model_failures), eval_path)
            return 1

    logger.info('Merge stage complete. Owner evaluation gate: %s', eval_path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
