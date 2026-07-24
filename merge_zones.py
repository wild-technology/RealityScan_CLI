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
   Acceptance = never-shrink (input membership union preserved).
   A rung that fuses restarts the ladder on the new state; convergence
   = a full ladder cycle with no fusion. There is NO fraction target -
   two saturated disjoint features are SUCCESS. --target is
   informational only.
3. Membership bookkeeping: merged-scene XMP exports are ORDINAL (B10),
   so membership is derived by ATTRIBUTION - merge never adds images,
   so a result component's members are the union of the input manifests
   that fused into it. Inputs are matched to result components by exact
   camera-count arithmetic (duplicate-path zone exports share no camera
   identity, so counts are exactly additive), tie-broken by bbox
   adjacency; every attribution is recorded with its confidence in the
   report. Per-component counts come from a count-based peel loop in
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
import shutil
import sys
import time
import logging

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from module_base.settings_store import SettingsStore
from modules import camera_registry
from modules import component_analysis
from modules import component_manifest
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


def partition_clusters(manifests: list[dict], logger) -> tuple[list[list[dict]], dict]:
    """Twin-drop, then connected components of the border graph.

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
    borders = component_analysis.find_borders(survivors)
    for entry in borders:
        a, b = entry['pair']
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
                     logger) -> tuple[list[dict], str]:
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
    was consumed."""
    by_key = {component_analysis.component_key(m): m for m in input_manifests}
    remaining = {k: m['camera_count'] for k, m in by_key.items()}
    consumed_counts: list[int] = []
    results, confidence = [], 'exact'

    order = sorted(range(len(peel_counts)), key=lambda i: -peel_counts[i])
    by_index: dict[int, dict] = {}
    for idx in order:
        count = peel_counts[idx]
        matched = None
        keys = sorted(remaining)
        subsets = []

        def search(i, acc, chosen):
            if acc == count:
                subsets.append(list(chosen))
                return
            if acc > count or i >= len(keys):
                return
            chosen.append(keys[i])
            search(i + 1, acc + remaining[keys[i]], chosen)
            chosen.pop()
            search(i + 1, acc, chosen)

        search(0, 0, [])
        if len(subsets) == 1:
            matched = subsets[0]
        elif len(subsets) > 1:
            matched = subsets[0]
            confidence = 'ambiguous'
            logger.warning('attribution ambiguous for count %d: %d candidate '
                           'subsets, took %s', count, len(subsets), matched)

        if matched is not None:
            members = set()
            for k in matched:
                members |= set(by_key[k]['images'])
                consumed_counts.append(remaining.pop(k))
            by_index[idx] = {'peel_index': idx, 'camera_count': count,
                             'inputs': matched, 'members': sorted(members),
                             'residual': False}
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
    except OSError as exc:
        logger.warning('Could not snapshot RealityScan.log: %s', exc)


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
                  min_size: int, logs_dir: str, logger) -> dict:
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
    rung = 0
    while rung < len(ladder):
        step = ladder[rung]
        attempt_no += 1
        adir = os.path.join(cdir, f'attempt_{attempt_no}_{step["label"]}')
        os.makedirs(adir, exist_ok=True)
        complist = os.path.join(adir, 'cluster.complist')
        with open(complist, 'w', encoding='utf-8', newline='\r\n') as f:
            f.write('\n'.join(m['rsalign'] for m in current) + '\n')

        logger.info('--- %s attempt %d: %s over %d components ---',
                    tag, attempt_no, step['label'], len(current))
        t0 = time.time()
        result = run_merge_workflow(
            cli, complist, adir, f'{tag}_m', step['mode'], step['settings'],
            log_path, params_path, images_root, logs_dir, harvest=True,
            logger=logger)
        snapshot_rs_log(os.path.join(adir, 'rslog.txt'), logger)
        registered, _r, _d = camera_registry.sanitize_and_census(images_root)

        sizes = peel_counts_from(adir)
        attributed, confidence = attribute_result(current, sizes, logger)
        adopted = [r for r in attributed if r['inputs']]
        residuals = [r for r in attributed if r['residual']]
        input_cams = sum(m['camera_count'] for m in current)
        adopted_cams = sum(r['camera_count'] for r in adopted)
        lost = input_cams - adopted_cams if adopted else None

        entry = {'attempt': attempt_no, 'label': step['label'],
                 'mode': step['mode'], 'workflow_success': result.success,
                 'errors': result.errors, 'census_leftover': registered,
                 'peel_sizes': sizes, 'attribution': confidence,
                 'input_count': len(current), 'adopted_count': len(adopted),
                 'residual_count': len(residuals),
                 'camera_delta': (adopted_cams - input_cams) if adopted else None,
                 'duration_s': round(time.time() - t0, 1)}
        record['attempts'].append(entry)

        fused = any(len(r['inputs']) >= 2 for r in adopted)
        accept = (result.success and adopted and fused
                  and confidence == 'exact'
                  and lost is not None and lost <= 0)
        if result.success and adopted and lost and lost > 0:
            logger.warning('%s attempt %d SHRANK by %d cameras - rejected '
                           '(never-shrink invariant)', tag, attempt_no, lost)
            entry['rejected'] = 'shrink'
        if result.success and fused and confidence != 'exact':
            logger.warning('%s attempt %d fused but attribution is %s - '
                           'rejected (membership would be untrustworthy)',
                           tag, attempt_no, confidence)
            entry['rejected'] = 'ambiguous_attribution'
        if accept:
            # Adopt the exported fused/unfused components (peel_index ->
            # <tag>_m_c<K>.rsalign); residual source copies stay on disk
            # but never travel forward.
            new_current = []
            for res in adopted:
                rsalign = os.path.join(
                    adir, f'{tag}_m_c{res["peel_index"]}.rsalign')
                if not os.path.isfile(rsalign):
                    logger.warning('expected export missing: %s', rsalign)
                    continue
                comp_name = f'{tag}_m_c{res["peel_index"]}'
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
                new_current.append(manifest)
            if len(new_current) == len(adopted):
                current = new_current
                logger.info('%s: fused to %d component(s) - ladder restarts',
                            tag, len(current))
                entry['accepted'] = True
                if len(current) == 1:
                    break
                rung = 0
                continue
            logger.warning('%s: exports incomplete (%d of %d) - treating '
                           'attempt as failed', tag, len(new_current),
                           len(adopted))
        rung += 1

    record['converged'] = True
    record['final_components'] = [{
        'key': component_analysis.component_key(m),
        'rsalign': m['rsalign'],
        'camera_count': m['camera_count'],
        'members': len(m.get('images') or []),
        'origin': ('fused' if m.get('attribution') else 'unfused input'),
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

    clusters, plan = partition_clusters(inputs, logger)
    total_images = count_unique_images(images_root)

    cli = RealityScanCLI(logger)
    report = {'schema': 2,
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
        record = merge_cluster(cli, cluster, i, output_dir, images_root,
                               ladder, min_size, logs_dir, logger)
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
    registered, _r, _d = camera_registry.sanitize_and_census(images_root)

    report['assembly'] = {
        'workflow_success': result.success,
        'errors': result.errors,
        'project': os.path.join(assembly_dir, f'{merged_name}.rsproj'),
        'census_after_update': registered,
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
    lines += ['',
              f'total cameras across components: {total_registered} '
              f'({100.0 * total_registered / max(total_images, 1):.1f}% of unique '
              f'images; informational target was {target:.0%})',
              'Multi-component outcomes are CORRECT for multi-feature dives '
              '(bow/hull). Evaluate each component in the GUI before models.']
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
        logger.info('auto_model: generating models for %d component(s)',
                    len(model_targets))
        proj = report['assembly']['project']
        for c in model_targets:
            comp_name = os.path.splitext(os.path.basename(c['rsalign']))[0]
            res = cli.run_batch_script('GenerateModel.bat',
                                       [proj, comp_name], logs_dir)
            report.setdefault('models', []).append(
                {'component': comp_name, 'success': res.success,
                 'errors': res.errors})
            flush()

    logger.info('Merge stage complete. Owner evaluation gate: %s', eval_path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
