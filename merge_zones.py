#!/usr/bin/env python3
"""Feature-aware cross-zone merge driver (reworked 2026-07-24).

Replaces the maximal-fraction ladder with the workflow the bow/hull
governing intent requires (HANDOFF workflow-evaluation queue;
docs/MERGE_REWORK_RECOMMENDATIONS.md):

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
3. Membership bookkeeping: merged-scene XMP exports are ORDINAL (B10),
   so membership is derived by ATTRIBUTION - merge never adds images,
   so a result component's members are the union of the input manifests
   that fused into it. Inputs are matched to result components by
   camera-count arithmetic (duplicate-path zone exports share no camera
   identity, so counts are additive), preferring exact subset sums and
   falling back to the smallest within-budget loss; every attribution is
   recorded with its confidence AND its accepted loss in the report. Per-component counts come from a count-based peel loop in
   the workflow (select maximal -> export -> census -> delete),
   run on the saved scene in memory only (AlignZone pattern).
4. Terminal state: ONE assembly project holding EVERY surviving
   component (fused or single) at its own maximum, georeferenced via
   union flight log + -update, saved + dated copy - then an
   EVALUATION READY report for the owner gate. Optional --auto_model
   runs GenerateModel per surviving component >= min size instead of
   stopping at the gate.

Usage:
    python merge_zones.py --components_root <aligned_components>
                          --images_root <batched_images_by_zone>
                          --output <merge_output_dir> [--name Merged]
                          [--min_size 50] [--project_label NA156_H2023]
                          [--visible true] [--auto_model false]
                          [--complist <file>]  (explicit component inputs)

All prompts default to the previous run's answers (rs_settings.json).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import logging

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from module_base.settings_store import SettingsStore
from modules import camera_registry
from modules import component_analysis
from modules import component_manifest
from modules import scale_oracle
from modules.flight_logs import utm_zone_from_flight_log_name, write_flight_log_params
from modules.realityscan_interface.realityscan_cli import (
    RealityScanCLI, METADATA_DIR, set_project_save_env)

COMPONENT_EXTENSIONS = ('.rsalign', '.rcalign')
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.heif')

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
                     logger, loss_tolerance: int = 0) -> tuple[list[dict], str]:
    """Map peel-loop component counts back to input-manifest subsets.

    CLI fact (smoke E2E, 2026-07-24): a merge/align leaves the SOURCE
    components in the scene alongside the freshly fused one - the peel
    of a fused 78+42 pair reads [120, 78, 42]. So peel entries are
    attributed LARGEST FIRST against the remaining inputs (duplicate-path
    exports share no camera identity, so a fusion's count is EXACTLY the
    sum of its inputs); an entry matching no remaining subset but equal
    to an already-consumed input's count is that input's RESIDUAL SOURCE
    component - expected, recorded, never adopted.

    Returns (results, confidence). Each result dict carries its
    peel_index (-> <name>_c<K>.rsalign), camera_count, inputs (consumed
    keys; empty for residuals), members (attributed basename union; None
    when unattributable), and residual flag. confidence 'exact' iff
    every entry was uniquely attributed or a residual and every input
    was consumed.

    `loss_tolerance` (absolute cameras, 0 = exact only) admits a subset whose
    sum EXCEEDS the peel count by up to that many cameras - i.e. a fusion that
    dropped a few marginal cameras. Without it a solver-lossy fusion is
    invisible: H2024's hull fused 4,860 of 4,865 cameras on every rung and was
    rejected all three times because 4,860 is not an exact subset sum
    (FINDINGS 2026-07-28). Exact matches always win; a lossy match is only
    considered when no exact one exists, and each adopted result carries the
    `loss` it was accepted with so the report can state it."""
    by_key = {component_analysis.component_key(m): m for m in input_manifests}
    remaining = {k: m['camera_count'] for k, m in by_key.items()}
    consumed_counts: list[int] = []
    results, confidence = [], 'exact'

    order = sorted(range(len(peel_counts)), key=lambda i: -peel_counts[i])
    by_index: dict[int, dict] = {}
    for idx in order:
        count = peel_counts[idx]
        matched, matched_loss = None, 0
        keys = sorted(remaining)
        exact_subsets, lossy_subsets = [], []

        def search(i, acc, chosen):
            if acc >= count:
                if acc == count:
                    exact_subsets.append(list(chosen))
                elif acc - count <= loss_tolerance and chosen:
                    lossy_subsets.append((acc - count, list(chosen)))
                return
            if i >= len(keys):
                return
            chosen.append(keys[i])
            search(i + 1, acc + remaining[keys[i]], chosen)
            chosen.pop()
            search(i + 1, acc, chosen)

        search(0, 0, [])
        if len(exact_subsets) == 1:
            matched = exact_subsets[0]
        elif len(exact_subsets) > 1:
            matched = exact_subsets[0]
            confidence = 'ambiguous'
            logger.warning('attribution ambiguous for count %d: %d candidate '
                           'subsets, took %s',
                           count, len(exact_subsets), matched)
        elif lossy_subsets:
            # Smallest loss first, then the LARGEST subset, so a genuine fusion
            # beats a lone input that happens to sit within tolerance.
            lossy_subsets.sort(key=lambda t: (t[0], -len(t[1])))
            matched_loss, matched = lossy_subsets[0]
            tied = [s for loss, s in lossy_subsets
                    if loss == matched_loss and len(s) == len(matched)]
            if len(tied) > 1:
                confidence = 'ambiguous'
                logger.warning('lossy attribution ambiguous for count %d: %d '
                               'candidates at loss %d, took %s',
                               count, len(tied), matched_loss, matched)
            else:
                logger.info('attributed peel count %d to %s with a %d-camera '
                            'loss (tolerance %d)',
                            count, matched, matched_loss, loss_tolerance)

        if matched is not None:
            members = set()
            for k in matched:
                members |= set(by_key[k]['images'])
                consumed_counts.append(remaining.pop(k))
            by_index[idx] = {'peel_index': idx, 'camera_count': count,
                             'inputs': matched, 'members': sorted(members),
                             'residual': False, 'loss': matched_loss}
        elif count in consumed_counts:
            consumed_counts.remove(count)
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

    zone_band = utm_zone_from_flight_log_name(zone_logs[0])
    if zone_band is None:
        raise ValueError(f'Flight log "{zone_logs[0]}" carries no UTM zone tag')
    zone, band = zone_band

    header, rows = None, {}
    for log_path in sorted(zone_logs):
        with open(log_path, encoding='utf-8') as f:
            lines = f.read().splitlines()
        if not lines:
            continue
        header = header or lines[0]
        for line in lines[1:]:
            if not line.strip():
                continue
            name = line.split(';')[0].strip('"').lower()
            if only_basenames is not None and name not in only_basenames:
                continue
            rows.setdefault(name, line)

    suffix = f'_{tag}' if tag else ''
    union_path = os.path.join(output_dir, f'flight_log{suffix}_{zone}{band}_UTM.txt')
    with open(union_path, 'w', encoding='utf-8', newline='\r\n') as f:
        f.write(header + '\n' + '\n'.join(rows.values()) + '\n')

    template = os.path.join(METADATA_DIR, 'FlightLogParams.xml')
    params_path = write_flight_log_params(
        template, os.path.join(output_dir, f'FlightLogParams_{zone}{band}.xml'),
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
                       logger):
    """One MergeZoneComponents.bat invocation with env plumbing."""
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
    return sizes


# ----------------------------------------------------------------------
# Cluster merge loop
# ----------------------------------------------------------------------

def merge_cluster(cli: RealityScanCLI, cluster: list[dict], cluster_idx: int,
                  output_dir: str, images_root: str, ladder: list[dict],
                  min_size: int, logs_dir: str, logger,
                  merge_scope: str = 'neighbour',
                  loss_tolerance_frac: float = 0.0,
                  pair_gate: str = 'overlap') -> dict:
    """Run the escalation ladder on one border-connected cluster until
    convergence. Returns the cluster record for the report, including the
    final component list (paths + manifests) for the assembly stage."""
    tag = f'cluster_{cluster_idx}'
    cdir = os.path.join(output_dir, tag)
    os.makedirs(cdir, exist_ok=True)

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
    log_path, params_path = build_union_flight_log(
        images_root, cdir, logger,
        only_basenames={b.lower() for b in members_union}, tag=tag)

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

        # Mechanism-aware rung selection - see effective_ladder_for. In
        # {c2, z4_c1, z4_c2} only c2-z4_c1 share imagery while z4_c2 merely
        # bbox-overlaps; a merge rung would glue all three, silently absorbing
        # an object whose relation is purely spatial. Align-only lets content
        # decide its fate (which is exactly what happened: align fused all
        # three on content, proving z4_c2 belonged).
        effective_ladder = effective_ladder_for(subset, ladder)
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
            complist = os.path.join(adir, 'cluster.complist')
            with open(complist, 'w', encoding='utf-8', newline='\r\n') as f:
                f.write('\n'.join(m['rsalign'] for m in subset) + '\n')

            logger.info('--- %s attempt %d: %s over %d components%s ---',
                        tag, attempt_no, step['label'], len(subset),
                        f' (target {target_key})' if target_key else '')
            t0 = time.time()
            export_name = fused_export_name(tag, attempt_no)
            result = run_merge_workflow(
                cli, complist, adir, export_name, step['mode'], step['settings'],
                log_path, params_path, images_root, logs_dir, harvest=True,
                logger=logger)
            snapshot_rs_log(os.path.join(adir, 'rslog.txt'), logger)
            registered, _r, _d = camera_registry.sanitize_and_census(images_root)

            sizes = peel_counts_from(adir)
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
                                                      loss_tolerance=tol)
            adopted = [r for r in attributed if r['inputs']]
            residuals = [r for r in attributed if r['residual']]
            adopted_cams = sum(r['camera_count'] for r in adopted)
            lost = input_cams - adopted_cams if adopted else None

            entry = {'attempt': attempt_no, 'label': step['label'],
                     'mode': step['mode'], 'workflow_success': result.success,
                     'errors': result.errors, 'census_leftover': registered,
                     'peel_sizes': sizes, 'attribution': confidence,
                     'scope': merge_scope, 'target': target_key,
                     'input_count': len(subset), 'adopted_count': len(adopted),
                     'residual_count': len(residuals),
                     'camera_delta': (adopted_cams - input_cams) if adopted else None,
                     'cameras_lost': lost,
                     'loss_tolerance': tol,
                     'loss_tolerance_frac': loss_tolerance_frac,
                     'rs_finalizing': entry_rs,
                     'duration_s': round(time.time() - t0, 1)}
            record['attempts'].append(entry)

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
                    entry['accepted'] = True
                    fused_this_target = True
                    logger.info('%s: fused %d -> %d; cluster now %d component(s)',
                                tag, len(subset), len(new_subset), len(current))
                    break
                logger.warning('%s: exports incomplete (%d of %d) - treating '
                               'attempt as failed', tag, len(new_subset),
                               len(adopted))
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
            exhausted.add(target_key)
            continue
        break

    record['converged'] = True
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
    logger.info('%s converged: %d final component(s)', tag, len(current))
    return record


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main() -> int:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger('merge_zones')
    settings = SettingsStore()

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--components_root', help='aligned_components directory')
    parser.add_argument('--images_root', help='batched_images_by_zone directory')
    parser.add_argument('--output', help='merge output directory')
    parser.add_argument('--name', default=None, help='assembly project name (default Merged)')
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
                        help='true = run GenerateModel per surviving component >= min_size')
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
    parser.add_argument('--scale_gate', default=None,
                        help='true (default) = refuse to MODEL a component whose '
                             'metric scale is out of band or unmeasurable')
    parser.add_argument('--scale_min', type=float, default=None,
                        help=f'lower scale bound (default {scale_oracle.DEFAULT_SCALE_MIN})')
    parser.add_argument('--scale_max', type=float, default=None,
                        help=f'upper scale bound (default {scale_oracle.DEFAULT_SCALE_MAX})')
    args = parser.parse_args()

    def ask(key, cli_value, fallback):
        if cli_value is not None:
            settings.set('merge', key, cli_value)
            return cli_value
        stored = settings.get('merge', key, fallback)
        if not sys.stdin.isatty():
            settings.set('merge', key, stored)
            return stored
        try:
            value = input(f'{key} [{stored}]: ').strip() or stored
        except EOFError:
            value = stored
        settings.set('merge', key, value)
        return value

    def truthy(v):
        return str(v).strip().lower() in ('1', 'true', 'yes', 'y')

    components_root = ask('components_root', args.components_root, '')
    images_root = ask('images_root', args.images_root, '')
    output_dir = ask('output', args.output, '')
    merged_name = ask('name', args.name, 'Merged')
    min_size = int(ask('min_size', args.min_size, 50))
    target = float(ask('target', args.target, 0.9))
    project_label = ask('project_label', args.project_label, '')
    visible = truthy(ask('visible', args.visible, 'true'))
    auto_model = truthy(ask('auto_model', args.auto_model, 'false'))
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

    if visible:
        os.environ['RS_HEADLESS'] = '0'
        logger.info('GUI-visible instances requested (RS_HEADLESS=0)')

    if project_label:
        projects_dir = set_project_save_env(images_root, project_label)
        logger.info('Daily project saves: %s', projects_dir)

    os.makedirs(output_dir, exist_ok=True)
    logs_dir = os.path.join(output_dir, 'logs')

    try:
        inputs = load_inputs(components_root, args.complist, logger)
    except (ValueError, FileNotFoundError) as exc:
        logger.error('%s', exc)
        return 1
    if not inputs:
        logger.error('No manifested components under %s', components_root)
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
              'clusters': []}

    def flush():
        with open(os.path.join(output_dir, 'merge_report.json'), 'w',
                  encoding='utf-8') as f:
            json.dump(report, f, indent=2)

    for i, cluster in enumerate(clusters):
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
                                   pair_gate=pair_gate)
        report['clusters'].append(record)
        flush()

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
        logger=logger)
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
    eval_path = os.path.join(output_dir, 'EVALUATION_READY.txt')
    with open(eval_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    logger.info('\n%s', '\n'.join(lines))
    report['evaluation_ready'] = eval_path
    flush()

    if not result.success:
        logger.error('Assembly workflow failed - see %s', assembly_dir)
        return 1

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
                logger.error('Model workflow FAILED for %s - RealityScan log '
                             'snapshot: %s', comp_name, rslog)
            report.setdefault('models', []).append(
                {'component': comp_name, 'success': res.success,
                 'errors': res.errors, 'rslog': rslog})
            flush()

    logger.info('Merge stage complete. Owner evaluation gate: %s', eval_path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
