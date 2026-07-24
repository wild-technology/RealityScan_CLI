#!/usr/bin/env python3
"""Iterative zone-component merge driver.

Loads every per-zone component exported by AlignZone.bat into a fresh
RealityScan scene and merges them into one georeferenced component,
escalating mechanism and flags until the registration target is met:

  attempt 1: -mergeComponents with sfmMergeGeoreferencedComponents=true
             (cheap component-level fuse by georeference + shared cameras;
             no new images added)
  attempt 2: -align (align/update) with sfmForceComponentRematch=true -
             feature-level fusion; the batcher's duplicated overlap bands
             give strong cross-zone visual ties
  attempt 3: attempt 2 + sfmImagesOverlap=High (broadest pair search)

Between attempts the pose-bearing XMP sidecars written by the census
export are restored to calibration-only content (camera_registry) so they
can never leak into later runs as exact-pose priors (bug B7). After each
attempt %LOCALAPPDATA%/Temp/RealityScan.log is snapshotted (each instance
boot truncates it - bug B6).

Success metric: cameras in the maximal merged component (pose-XMP census)
as a fraction of the unique images across all zone folders.

Usage:
    python merge_zones.py --components_root <aligned_components>
                          --images_root <batched_images_by_zone>
                          --output <merge_output_dir> [--name Merged]
                          [--min_size 50] [--target 0.9]

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
from modules.flight_logs import utm_zone_from_flight_log_name, write_flight_log_params
from modules.realityscan_interface.realityscan_cli import (
    RealityScanCLI, METADATA_DIR, set_project_save_env)

try:
    from modules import component_analysis, component_manifest
except ImportError:  # manifests are an enhancement, not a requirement
    component_analysis = component_manifest = None

COMPONENT_EXTENSIONS = ('.rsalign', '.rcalign')
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.heif')

ATTEMPTS = [
    {
        'label': 'merge_georef',
        'mode': 'merge',
        'settings': ['sfmMergeGeoreferencedComponents:true',
                     'sfmEnableCameraPrior:true'],
    },
    {
        'label': 'align_rematch',
        'mode': 'align',
        'settings': ['sfmMergeGeoreferencedComponents:true',
                     'sfmEnableCameraPrior:true',
                     'sfmForceComponentRematch:true'],
    },
    {
        'label': 'align_rematch_high_overlap',
        'mode': 'align',
        'settings': ['sfmMergeGeoreferencedComponents:true',
                     'sfmEnableCameraPrior:true',
                     'sfmForceComponentRematch:true',
                     'sfmImagesOverlap:High'],
    },
]


def find_zone_components(components_root: str) -> list[str]:
    """Every component file under the per-zone export folders, at its
    ORIGINAL location (relocated .rsalign imports hang forever - B1)."""
    found = []
    for root, _dirs, files in os.walk(components_root):
        for f in sorted(files):
            if f.lower().endswith(COMPONENT_EXTENSIONS):
                found.append(os.path.join(root, f))
    return found


def resolve_twins_and_plan(components_root: str, components: list[str],
                           logger) -> tuple[list[str], dict]:
    """Twin-resolve the component list via manifests, when available.

    A component whose image set is fully contained in the kept union
    (no unique images) is dropped from the merge input - it is the
    weak twin of an overlap band, rigid merge cannot fix its internal
    distortion, and its cameras would pollute meshing in that strip
    (FINDINGS.md 2026-07-23). Components with ANY unique images are
    never dropped. Without manifests, everything is kept.

    Returns (kept component paths, decisions dict for the report).
    """
    if component_analysis is None or component_manifest is None:
        return components, {'manifests': 'unavailable - all components kept'}

    manifests = component_analysis.load_manifests(components_root)
    if not manifests:
        return components, {'manifests': 'none found - all components kept'}

    try:
        plan = component_analysis.merge_plan(manifests)
    except (ValueError, KeyError) as exc:
        logger.warning('manifest analysis failed (%s) - all components kept', exc)
        return components, {'manifests': f'analysis failed: {exc}'}

    # Discards are reported by 'zone/component' key; map back to the
    # .rsalign path through the manifests.
    key_to_rsalign = {component_analysis.component_key(m): m.get('rsalign', '')
                      for m in manifests}
    dropped_rsaligns = set()
    for decision in plan.get('twin_resolutions', []):
        for discard in decision.get('discards', []):
            key = discard.get('component', '')
            rsalign = key_to_rsalign.get(key)
            if rsalign:
                dropped_rsaligns.add(os.path.normcase(os.path.abspath(rsalign)))
                logger.warning('Twin drop: %s (%s)', key,
                               discard.get('reason', 'no unique images'))

    kept = [c for c in components
            if os.path.normcase(os.path.abspath(c)) not in dropped_rsaligns]
    if len(kept) != len(components):
        logger.info('Twin resolution kept %d of %d components',
                    len(kept), len(components))
    return kept, plan


def count_unique_images(images_root: str) -> int:
    """Unique image basenames across the zone folders (overlap copies are
    duplicated between zones; identity is the basename)."""
    names = set()
    for root, _dirs, files in os.walk(images_root):
        for f in files:
            if f.lower().endswith(IMAGE_EXTENSIONS):
                names.add(f.lower())
    return len(names)


def build_union_flight_log(images_root: str, output_dir: str, logger) -> tuple[str, str]:
    """Union of the per-zone flight logs (deduped by image basename) plus
    an auto-generated CRS params XML.

    The merge scene MUST have these constraints imported: a merged
    component is a new component, and without in-scene constraints
    RealityScan produces it non-georeferenced regardless of the source
    components' own georeferencing (observed NA156 H2023). Returns
    (union_log_path, params_xml_path).
    """
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

    header = None
    rows: dict[str, str] = {}
    for log_path in sorted(zone_logs):
        with open(log_path, encoding='utf-8') as f:
            lines = f.read().splitlines()
        if not lines:
            continue
        if header is None:
            header = lines[0]
        for line in lines[1:]:
            if not line.strip():
                continue
            name = line.split(';')[0].strip('"').lower()
            rows.setdefault(name, line)

    union_path = os.path.join(output_dir, f'flight_log_{zone}{band}_UTM.txt')
    with open(union_path, 'w', encoding='utf-8', newline='\r\n') as f:
        f.write(header + '\n' + '\n'.join(rows.values()) + '\n')

    template = os.path.join(METADATA_DIR, 'FlightLogParams.xml')
    params_path = write_flight_log_params(
        template, os.path.join(output_dir, f'FlightLogParams_{zone}{band}.xml'),
        zone, band)
    logger.info('Union flight log: %d rows from %d zone logs -> %s (CRS: UTM %d%s)',
                len(rows), len(zone_logs), union_path, zone, band)
    return union_path, params_path


def snapshot_rs_log(dest: str, logger) -> None:
    src = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Temp', 'RealityScan.log')
    try:
        shutil.copyfile(src, dest)
    except OSError as exc:
        logger.warning('Could not snapshot RealityScan.log: %s', exc)


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger('merge_zones')
    settings = SettingsStore()

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--components_root', help='aligned_components directory (per-zone subfolders)')
    parser.add_argument('--images_root', help='batched_images_by_zone directory (census + sidecar hygiene)')
    parser.add_argument('--output', help='merge output directory')
    parser.add_argument('--name', default=None, help='merged component name (default Merged)')
    parser.add_argument('--min_size', type=int, default=None, help='min component size for exports (default 50)')
    parser.add_argument('--target', type=float, default=None,
                        help='stop when maximal component registers this fraction of unique images (default 0.9)')
    parser.add_argument('--project_label', default=None,
                        help='expedition_dive label for the RC_projects daily save schema (e.g. NA156_H2023)')
    args = parser.parse_args()

    def ask(key, cli_value, fallback):
        if cli_value is not None:
            settings.set('merge', key, cli_value)
            return cli_value
        stored = settings.get('merge', key, fallback)
        # Unattended runs must never block on (or crash from) input():
        # without a TTY, take the stored/fallback value silently.
        if not sys.stdin.isatty():
            settings.set('merge', key, stored)
            return stored
        try:
            value = input(f'{key} [{stored}]: ').strip() or stored
        except EOFError:
            # Hidden consoles report isatty()=True with an EOF stdin
            # (observed on backgrounded runs) - fall back silently.
            value = stored
        settings.set('merge', key, value)
        return value

    components_root = ask('components_root', args.components_root, '')
    images_root = ask('images_root', args.images_root, '')
    output_dir = ask('output', args.output, '')
    merged_name = ask('name', args.name, 'Merged')
    min_size = int(ask('min_size', args.min_size, 50))
    target = float(ask('target', args.target, 0.9))
    project_label = ask('project_label', args.project_label, '')

    if project_label:
        projects_dir = set_project_save_env(images_root, project_label)
        logger.info('Daily project saves: %s ({label}_merged_YYYYMMDD)', projects_dir)

    components = find_zone_components(components_root)
    if len(components) < 2:
        logger.error('Need at least 2 components under %s, found %d '
                     '(a single component needs no merge)', components_root, len(components))
        return 1

    # Twin resolution: drop weak twins (no unique images) before they can
    # pollute the merged component; keep the analysis plan for the report.
    components, twin_plan = resolve_twins_and_plan(components_root, components, logger)
    if len(components) < 2:
        logger.error('Fewer than 2 components remain after twin resolution '
                     '- nothing to merge')
        return 1

    total_images = count_unique_images(images_root)
    if total_images == 0:
        logger.error('No images found under %s', images_root)
        return 1

    os.makedirs(output_dir, exist_ok=True)
    logger.info('Merging %d components; %d unique images; target %.0f%%',
                len(components), total_images, target * 100)

    # Constraints for georeferencing the merged component (see
    # build_union_flight_log). Passed via env because the workflow's
    # %1-%9 argument slots are exhausted.
    union_log, union_params = build_union_flight_log(images_root, output_dir, logger)
    os.environ['RS_MERGE_FLIGHT_LOG'] = union_log
    os.environ['RS_MERGE_FLIGHT_LOG_PARAMS'] = union_params

    cli = RealityScanCLI(logger)
    report = {'components_in': components, 'unique_images': total_images,
              'target_fraction': target, 'twin_plan': twin_plan,
              'attempts': []}

    final_success = False
    for attempt in ATTEMPTS:
        attempt_dir = os.path.join(output_dir, f'attempt_{attempt["label"]}')
        os.makedirs(attempt_dir, exist_ok=True)

        complist_path = os.path.join(attempt_dir, 'zones.complist')
        with open(complist_path, 'w', encoding='ascii', newline='\r\n') as f:
            f.write('\n'.join(components) + '\n')

        logger.info('--- merge attempt: %s (mode=%s) ---', attempt['label'], attempt['mode'])
        bat_args = [complist_path, attempt_dir, merged_name, attempt['mode'],
                    str(min_size)] + attempt['settings']
        result = cli.run_batch_script('MergeZoneComponents.bat', bat_args,
                                      os.path.join(output_dir, 'logs'))

        snapshot_rs_log(os.path.join(attempt_dir, 'realityscan_log_snapshot.txt'), logger)

        # Census BEFORE judging: the export writes pose sidecars next to
        # the images; count them, then restore calibration-only content.
        registered, _restored, removed = camera_registry.sanitize_and_census(images_root)
        if removed:
            logger.warning('%d pose sidecars of unknown cameras deleted', removed)

        fraction = registered / total_images if total_images else 0.0
        merged_component = os.path.join(attempt_dir, f'{merged_name}.rsalign')
        leftover_dir = os.path.join(attempt_dir, 'all_components')
        leftovers = (len([f for f in os.listdir(leftover_dir)
                          if f.lower().endswith(COMPONENT_EXTENSIONS)])
                     if os.path.isdir(leftover_dir) else None)

        attempt_report = {
            'label': attempt['label'],
            'mode': attempt['mode'],
            'settings': attempt['settings'],
            'workflow_success': result.success,
            'errors': result.errors,
            'duration_seconds': round(result.duration_seconds, 1),
            'registered_cameras': registered,
            'registered_fraction': round(fraction, 4),
            'merged_component': merged_component if os.path.isfile(merged_component) else None,
            'all_components_exported': leftovers,
        }
        report['attempts'].append(attempt_report)
        logger.info('attempt %s: success=%s registered=%d/%d (%.1f%%)',
                    attempt['label'], result.success, registered,
                    total_images, fraction * 100)

        if result.success and fraction >= target:
            report['final'] = attempt_report
            final_success = True
            break

    report_path = os.path.join(output_dir, 'merge_report.json')
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2)
    logger.info('Report: %s', report_path)

    if not final_success:
        logger.error('No merge attempt reached the %.0f%% target - inspect '
                     'merge_report.json and the per-attempt RealityScan log '
                     'snapshots. Escalation options: setFeatureSource '
                     'experiments per camera (per-image LITERAL selectImage '
                     'union - regexp/glob forms silently select nothing in '
                     'this build, see FINDINGS.md and GrowZone.bat), '
                     'distortion-model upgrade + re-align (see '
                     'docs/settings-evaluation-2026-07.md).', target * 100)
        return 1

    merged_path = report['final'].get('merged_component')
    logger.info('Merge complete: %s', merged_path or '<component file not found>')
    if merged_path:
        logger.info('Next: GenerateModel.bat "%s" "%s"',
                    os.path.join(os.path.dirname(merged_path),
                                 f'{merged_name}.rsproj'), merged_name)
    return 0


if __name__ == '__main__':
    sys.exit(main())
