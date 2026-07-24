#!/usr/bin/env python3
"""Within-zone component growth driver.

Implements the within-zone half of the "Revised order of operations"
(docs/merge-growth-strategy-2026-07.md) on ONE zone's ORIGINAL aligned
scene (features cached, image identity intact - never a scene rebuilt
from component imports, which silently lacks the orphan images):

  1. Checkpoint: snapshot the scene bundle and export the current
     components (+ manifests when available).
  2. Global re-align with ALL images enabled; accept/rollback on the
     never-shrink invariant (no previously registered image lost AND
     registered camera count >= before).
  3. Rigid -mergeComponents consolidation (cannot shrink) + stale
     component cleanup (manifest-verified containment).
  4. Per-component growth loop, largest first: disable all images,
     enable the component's images (featureSource 1 = component
     features) plus the zone's orphan images (feature defaults), align,
     accept/rollback, stale cleanup. Iterate while passes gain cameras,
     capped by --max_passes.
  5. Export final components + manifests; write grow_report.json.

Checkpoint/rollback design (owner-mandated 2026-07-23): the checkpoint
is a plain file copy of the .rsproj plus its companion data folder (the
sibling directory named after the project stem, holding sfmN.dat etc.),
restored to the SAME path on rollback. The officially sanctioned
export/fix/reimport round trip (components.htm) is NOT used for
rollback: importing components into a fresh project does not bring the
images absent from those components, so the round trip would silently
lose every orphan image - the precious missing-link candidates this
stage exists to register. It remains a manual fallback only.

Usage:
    py -3.13 grow_zone.py --scene <zone .rsproj> --images_root <zone images>
        [--components_dir <AlignZone exports with manifests>]
        [--output <dir>] [--min_size 50] [--max_passes 8]
        [--feature_source 1] [--selection_cmds editsel|legacy]
        [--lock_anchor] [--skip_global] [--project_label NA156_H2023]

All prompts default to the previous run's answers (rs_settings.json).
RS_HEADLESS is passed through untouched (RS_HEADLESS=0 boots the
instance with a visible GUI). --lock_anchor (inpPose=3 on the component
being grown) stays OFF by default until hardening cell U18 verifies the
locked-pose behavior.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from module_base.settings_store import SettingsStore
from modules import camera_registry
from modules.realityscan_interface.realityscan_cli import (
    RealityScanCLI, set_project_save_env)

# Parallel-developed bookkeeping modules (manifest contract schema 1;
# twin/orphan analysis). Import-guarded so this driver runs - degraded
# but safely - until they land.
try:
    from modules import component_manifest  # type: ignore
except Exception:  # pragma: no cover - module still in development
    component_manifest = None
try:
    from modules import component_analysis  # type: ignore
except Exception:  # pragma: no cover - module still in development
    component_analysis = None

COMPONENT_EXTENSIONS = ('.rsalign', '.rcalign')
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.heif')
MANIFEST_SCHEMA = 1


# ----------------------------------------------------------------------
# Image index and registration census
# ----------------------------------------------------------------------

def build_image_index(images_root: str) -> tuple[dict[str, str], dict[str, str]]:
    """(basename_lower -> full path, stem_lower -> basename_lower) for
    every image under the zone root. Identity is the basename (the
    batcher duplicates overlap images between zones by copy)."""
    by_basename: dict[str, str] = {}
    by_stem: dict[str, str] = {}
    for root, _dirs, files in os.walk(images_root):
        for f in files:
            if f.lower().endswith(IMAGE_EXTENSIONS):
                base = f.lower()
                by_basename.setdefault(base, os.path.join(root, f))
                by_stem.setdefault(os.path.splitext(base)[0], base)
    return by_basename, by_stem


def registered_basenames(images_root: str, stem_index: dict[str, str],
                         logger) -> set[str]:
    """Registration census: image basenames whose XMP sidecar carries a
    pose (-exportXMP writes pose entries only for registered cameras).
    Read-only - callers must follow up with
    camera_registry.sanitize_and_census so pose sidecars can never leak
    into later adds as exact-pose priors (bug B7)."""
    names: set[str] = set()
    unmapped = 0
    for root, _dirs, files in os.walk(images_root):
        for f in files:
            if not f.lower().endswith('.xmp'):
                continue
            try:
                with open(os.path.join(root, f), encoding='utf-8',
                          errors='replace') as fh:
                    content = fh.read()
            except OSError:
                continue
            if 'xcr:Position' not in content:
                continue
            base = stem_index.get(os.path.splitext(f)[0].lower())
            if base is None:
                unmapped += 1
                continue
            names.add(base)
    if unmapped:
        logger.warning('census: %d pose sidecars had no matching image '
                       'under the images root', unmapped)
    return names


def take_census(images_root: str, stem_index: dict[str, str], logger) -> set[str]:
    names = registered_basenames(images_root, stem_index, logger)
    pose_count, _restored, removed = camera_registry.sanitize_and_census(images_root)
    if removed:
        logger.warning('%d pose sidecars of unknown cameras deleted', removed)
    if pose_count != len(names):
        logger.info('census: %d pose sidecars, %d mapped to images',
                    pose_count, len(names))
    return names


# ----------------------------------------------------------------------
# Scene checkpoint / rollback (owner-mandated design: bundle file copy)
# ----------------------------------------------------------------------

def scene_bundle(scene_path: str) -> list[str]:
    """The .rsproj plus its companion data folder. A RealityScan save
    produces a sibling directory named exactly after the project stem
    (e.g. zone_1/ next to zone_1.rsproj) holding the bulky state as flat
    .dat blobs (sfmN.dat, appConfig0.dat, controlpoints0.dat, ...) -
    verified on D:/na156_h2023/aligned_components 2026-07-23. The extra
    candidates are defensive, in case a future build renames the folder."""
    stem = os.path.splitext(scene_path)[0]
    candidates = [scene_path, stem, stem + '.Data', scene_path + '.data']
    return [p for p in candidates if os.path.exists(p)]


def checkpoint_scene(scene_path: str, checkpoints_dir: str, tag: str,
                     logger) -> str:
    dest = os.path.join(checkpoints_dir, tag)
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    for src in scene_bundle(scene_path):
        target = os.path.join(dest, os.path.basename(src))
        if os.path.isdir(src):
            shutil.copytree(src, target)
        else:
            shutil.copy2(src, target)
    logger.info('checkpoint "%s" -> %s', tag, dest)
    return dest


def restore_scene(scene_path: str, checkpoints_dir: str, tag: str, logger) -> None:
    """Rollback = restore the pre-pass scene snapshot to the SAME path.

    Deliberately NOT the export/fix/reimport round trip: reimported
    components do not contain the never-registered orphan images, so a
    round-trip rollback would silently drop them from the scene
    (owner-confirmed 2026-07-23). Relocated .rsalign imports also hang
    the instance (hard rule 7). The bundle copy avoids both hazards."""
    src_dir = os.path.join(checkpoints_dir, tag)
    if not os.path.isdir(src_dir):
        raise FileNotFoundError(f'checkpoint "{tag}" not found in {checkpoints_dir}')
    # Remove the rejected bundle first so stale sidecar data can never
    # mix with the restored snapshot.
    for cur in scene_bundle(scene_path):
        if os.path.isdir(cur):
            shutil.rmtree(cur)
        else:
            os.remove(cur)
    scene_dir = os.path.dirname(os.path.normpath(scene_path))
    for name in os.listdir(src_dir):
        src = os.path.join(src_dir, name)
        target = os.path.join(scene_dir, name)
        if os.path.isdir(src):
            shutil.copytree(src, target)
        else:
            shutil.copy2(src, target)
    logger.info('rolled back scene from checkpoint "%s"', tag)


def prune_checkpoints(checkpoints_dir: str, keep: set[str], logger) -> None:
    """Scene bundles are large (multi-GB); keep only the initial
    checkpoint and the most recent one."""
    if not os.path.isdir(checkpoints_dir):
        return
    for name in os.listdir(checkpoints_dir):
        if name in keep:
            continue
        path = os.path.join(checkpoints_dir, name)
        if os.path.isdir(path):
            try:
                shutil.rmtree(path)
                logger.info('pruned checkpoint "%s"', name)
            except OSError as exc:
                logger.warning('could not prune checkpoint %s: %s', name, exc)


# ----------------------------------------------------------------------
# Manifests (contract: modules/component_manifest.py, schema 1)
# ----------------------------------------------------------------------

def load_contract_manifests(directory: str, logger) -> dict[str, dict]:
    """Read schema-1 manifest JSONs from a component export directory ->
    {component_name: manifest}. Reads the CONTRACT directly so the driver
    works whether or not component_manifest is importable yet."""
    manifests: dict[str, dict] = {}
    if not directory or not os.path.isdir(directory):
        return manifests
    for root, _dirs, files in os.walk(directory):
        for f in sorted(files):
            if not f.lower().endswith('.json'):
                continue
            path = os.path.join(root, f)
            try:
                with open(path, encoding='utf-8') as fh:
                    data = json.load(fh)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict) or data.get('schema') != MANIFEST_SCHEMA:
                continue
            name = data.get('component')
            images = data.get('images')
            if not name or not isinstance(images, list):
                continue
            data['images'] = [str(i).lower() for i in images]
            data.setdefault('camera_count', len(data['images']))
            manifests[name] = data
    if manifests:
        logger.info('loaded %d component manifests from %s', len(manifests), directory)
    return manifests


def try_build_manifests(export_dir: str, zone: str, logger) -> bool:
    """Growth exports CANNOT rebuild identity manifests: stem-named
    per-component membership only exists via AlignZone.bat's in-session
    successive-difference harvest (-exportXMPForSelectedComponent is
    always ordinal - FINDINGS B10 FINAL FORM). This is an honest no-op
    kept as the single place that documents WHY refresh is impossible
    here; post-growth manifests stay approximate until an AlignZone
    identity pass re-runs on the grown scene."""
    return False


def write_manifest(manifest: dict, directory: str) -> str:
    """Write a manifest next to its component using the CONTRACT naming
    (<rsalign>.manifest.json) so component_analysis.load_manifests and
    merge_zones can find it. Review finding 2026-07-24: the previous
    '<component>.json' naming made growth manifests invisible to the
    merge stage. Approximate membership is flagged in the manifest
    itself so twin resolution can refuse to discard on fuzzy data."""
    safe = re.sub(r'[^A-Za-z0-9._ -]', '_', str(manifest['component']))
    rsalign_guess = manifest.get('rsalign') or os.path.join(directory, f'{safe}.rsalign')
    path = os.path.join(directory, os.path.basename(rsalign_guess) + '.manifest.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
    return path


def new_history_entry(event: str, **detail) -> dict:
    entry = {'time': time.strftime('%Y-%m-%dT%H:%M:%S'), 'event': event}
    entry.update(detail)
    return entry


# ----------------------------------------------------------------------
# Orphans and stale components
# ----------------------------------------------------------------------

def compute_orphans(manifests: dict[str, dict], all_basenames: set[str],
                    logger) -> set[str]:
    """Images in the zone that belong to no component - the missing-link
    candidates every growth pass keeps enabled."""
    if component_analysis is not None:
        fn = getattr(component_analysis, 'orphan_images', None)
        if callable(fn):
            for call_args in ((list(manifests.values()), all_basenames),
                              (list(manifests.values()),)):
                try:
                    return {str(b).lower() for b in fn(*call_args)}
                except TypeError:
                    continue
                except Exception as exc:
                    logger.warning('component_analysis.orphan_images failed: %s', exc)
                    break
    covered: set[str] = set()
    for m in manifests.values():
        covered.update(m['images'])
    return set(all_basenames) - covered


def stale_components(manifests: dict[str, dict], untrusted: set[str],
                     logger) -> list[str]:
    """Components whose image set is fully contained in another
    component's: "no unique images" makes them discardable by the
    recipe's own rule. STRICT containment only - the quality-weighted
    twin scan (component_analysis.find_twins/choose_keeper) is a
    follow-up once that API lands. Components whose manifests are
    census-approximate (`untrusted`) are excluded from BOTH sides, so an
    inflated approximation can never justify deleting a real component."""
    names = [n for n in manifests if n not in untrusted]
    stale: set[str] = set()
    for a in names:
        if a in stale:
            continue
        ia = set(manifests[a]['images'])
        if not ia:
            continue
        for b in names:
            if b == a or b in stale:
                continue
            ib = set(manifests[b]['images'])
            # keeper on exact ties: the lexicographically first name
            if ia <= ib and (len(ia) < len(ib) or a > b):
                stale.add(a)
                logger.info('component "%s" (%d images) is contained in '
                            '"%s" (%d images) - stale', a, len(ia), b, len(ib))
                break
    return sorted(stale)


# ----------------------------------------------------------------------
# List files for the workflow (.imagelist / component-name lists)
# ----------------------------------------------------------------------

def write_imagelist(path: str, basenames: set[str],
                    basename_index: dict[str, str], logger) -> int:
    """Full image paths, one per line, ASCII + CRLF (cmd's for /f reads
    the file as ANSI bytes; every path in this pipeline is ASCII by
    convention - non-ASCII paths fail loudly here rather than corrupting
    the selection)."""
    lines = []
    missing = 0
    for base in sorted(basenames):
        full = basename_index.get(base)
        if full is None:
            missing += 1
            continue
        lines.append(full)
    if missing:
        logger.warning('%d listed images not found under the images root '
                       '(skipped)', missing)
    if not lines:
        raise ValueError(f'imagelist would be empty: {path}')
    with open(path, 'w', encoding='ascii', newline='\r\n') as f:
        f.write('\n'.join(lines) + '\n')
    return len(lines)


def write_namelist(path: str, names: list[str]) -> None:
    with open(path, 'w', encoding='ascii', newline='\r\n') as f:
        f.write('\n'.join(names) + '\n')


def exported_components(export_dir: str) -> dict[str, str]:
    """{component name (file stem): path} for .rsalign files exported to
    export_dir. RealityScan names exports after components."""
    out: dict[str, str] = {}
    if os.path.isdir(export_dir):
        for f in sorted(os.listdir(export_dir)):
            if f.lower().endswith(COMPONENT_EXTENSIONS):
                out[os.path.splitext(f)[0]] = os.path.join(export_dir, f)
    return out


# ----------------------------------------------------------------------
# Driver
# ----------------------------------------------------------------------

def main() -> int:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger('grow_zone')
    settings = SettingsStore()

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--scene', help='zone .rsproj - the ORIGINAL aligned scene')
    parser.add_argument('--images_root', help='zone image directory (census + orphans)')
    parser.add_argument('--components_dir', default=None,
                        help='AlignZone component exports with manifests (blank to bootstrap)')
    parser.add_argument('--output', help='growth working/output directory')
    parser.add_argument('--min_size', type=int, default=None,
                        help='min component size for exports (default 50)')
    parser.add_argument('--max_passes', type=int, default=None,
                        help='cap on per-component growth passes (default 8)')
    parser.add_argument('--feature_source', type=int, default=None,
                        help='featureSource for the component being grown '
                             '(default 1 = component features; orphans stay default)')
    parser.add_argument('--selection_cmds', choices=('editsel', 'legacy'), default=None,
                        help='editsel: -editInputSelection inpEnabled/aligFeaturesMode '
                             '(default); legacy: -enableAlignment/-setFeatureSource')
    parser.add_argument('--lock_anchor', action='store_true',
                        help='lock the grown component poses (inpPose=3) during its '
                             'align - EXPERIMENTAL, off until U18 verifies it')
    parser.add_argument('--skip_global', action='store_true',
                        help='skip the opening global re-align pass')
    parser.add_argument('--project_label', default=None,
                        help='expedition_dive label for the RC_projects daily-save '
                             'schema (e.g. NA156_H2023)')
    args = parser.parse_args()

    def ask(key, cli_value, fallback):
        if cli_value is not None:
            settings.set('grow', key, cli_value)
            return cli_value
        stored = settings.get('grow', key, fallback)
        # Unattended runs must never block on (or crash from) input():
        # without a TTY, take the stored/fallback value silently.
        if not sys.stdin.isatty():
            settings.set('grow', key, stored)
            return stored
        try:
            value = input(f'{key} [{stored}]: ').strip() or stored
        except EOFError:
            # Hidden consoles report isatty()=True with an EOF stdin
            # (observed on backgrounded runs) - fall back silently.
            value = stored
        settings.set('grow', key, value)
        return value

    scene = ask('scene', args.scene, '')
    images_root = ask('images_root', args.images_root, '')
    components_dir = ask('components_dir', args.components_dir, '')
    output_dir = ask('output', args.output, '')
    min_size = int(ask('min_size', args.min_size, 50))
    max_passes = int(ask('max_passes', args.max_passes, 8))
    feature_source = int(ask('feature_source', args.feature_source, 1))
    project_label = ask('project_label', args.project_label, '')

    if not os.path.isfile(scene):
        logger.error('scene not found: %s', scene)
        return 1
    if not os.path.isdir(images_root):
        logger.error('images root not found: %s', images_root)
        return 1

    zone = os.path.splitext(os.path.basename(scene))[0]
    os.makedirs(output_dir, exist_ok=True)
    checkpoints_dir = os.path.join(output_dir, 'checkpoints')
    passes_dir = os.path.join(output_dir, 'passes')
    logs_dir = os.path.join(output_dir, 'logs')
    for d in (checkpoints_dir, passes_dir, logs_dir):
        os.makedirs(d, exist_ok=True)

    if project_label:
        projects_dir = set_project_save_env(
            os.path.dirname(os.path.normpath(images_root)), project_label)
        logger.info('Daily project saves: %s ({label}_%s_YYYYMMDD)', projects_dir, zone)

    # Selection-command strategy + experimental lock anchor, consumed by
    # GrowZone.bat via the environment (RS_HEADLESS passes through the
    # same way, untouched).
    os.environ['RS_GROW_SELECT_CMDS'] = args.selection_cmds or 'editsel'
    if args.lock_anchor:
        os.environ['RS_GROW_LOCK_ANCHOR'] = '1'
        logger.warning('lock-anchor mode is ON (inpPose=3) - unverified '
                       'until hardening cell U18')
    else:
        os.environ.pop('RS_GROW_LOCK_ANCHOR', None)

    basename_index, stem_index = build_image_index(images_root)
    all_basenames = set(basename_index)
    if not all_basenames:
        logger.error('no images found under %s', images_root)
        return 1
    logger.info('zone "%s": %d unique images', zone, len(all_basenames))

    manifests = load_contract_manifests(components_dir, logger)
    untrusted: set[str] = set()          # census-approximate manifests
    last_export: dict[str, str] = {}     # component -> latest .rsalign path

    cli = RealityScanCLI(logger, settings)
    report = {
        'zone': zone,
        'scene': scene,
        'images_root': images_root,
        'unique_images': len(all_basenames),
        'min_size': min_size,
        'max_passes': max_passes,
        'feature_source': feature_source,
        'selection_cmds': os.environ['RS_GROW_SELECT_CMDS'],
        'lock_anchor': bool(args.lock_anchor),
        'passes': [],
    }
    report_path = os.path.join(output_dir, 'grow_report.json')

    def save_report():
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2)

    def run_pass(tag: str, mode: str, payload: str = None,
                 fsource: str = '-', export_dir: str = None,
                 secondary: str = None):
        bat_args = [scene, mode, payload or '-', str(fsource),
                    export_dir or '-', str(min_size), secondary or '-']
        return cli.run_batch_script('GrowZone.bat', bat_args, logs_dir)

    def record(entry: dict):
        report['passes'].append(entry)
        save_report()

    def note_exports(export_dir: str):
        for name, path in exported_components(export_dir).items():
            last_export[name] = path

    # ------------------------------------------------------------------
    # 1. Checkpoint: scene snapshot + component export + baseline census
    # ------------------------------------------------------------------
    checkpoint_scene(scene, checkpoints_dir, 'initial', logger)

    baseline_export = os.path.join(passes_dir, 'checkpoint_export')
    logger.info('--- stage 1: checkpoint export ---')
    result = run_pass('checkpoint', 'export', export_dir=baseline_export)
    if not result.success:
        logger.error('checkpoint export failed: %s', result.errors)
        record({'tag': 'checkpoint', 'mode': 'export', 'accepted': False,
                'workflow_success': False, 'errors': result.errors})
        return 1
    note_exports(baseline_export)
    baseline = take_census(images_root, stem_index, logger)
    if not baseline:
        logger.error('checkpoint census found no registered cameras - is '
                     '%s an aligned zone scene?', scene)
        return 1
    if not manifests:
        manifests = load_contract_manifests(baseline_export, logger)
    if not manifests:
        logger.warning('no component manifests available - per-component '
                       'growth passes and stale cleanup will be SKIPPED '
                       '(global re-align and rigid merge still run)')
    record({'tag': 'checkpoint', 'mode': 'export', 'accepted': True,
            'workflow_success': True,
            'registered': len(baseline),
            'components_exported': len(exported_components(baseline_export)),
            'manifests': len(manifests),
            'duration_seconds': round(result.duration_seconds, 1)})
    logger.info('baseline: %d registered images, %d component manifests',
                len(baseline), len(manifests))

    def evaluate(tag: str, before: set[str], after: set[str],
                 workflow_ok: bool) -> tuple[bool, list[str]]:
        """Never-shrink invariant: no previously registered image lost
        AND camera count >= before."""
        lost = sorted(before - after)
        ok = workflow_ok and not lost and len(after) >= len(before)
        if lost:
            logger.warning('pass %s lost %d previously registered images '
                           '(e.g. %s)', tag, len(lost), lost[:3])
        return ok, lost

    def cleanup_stale(reason: str) -> None:
        """Delete components with no unique images (containment-verified).
        Non-fatal: a failed cleanup restores the checkpoint and moves on."""
        if not manifests:
            return
        stale = stale_components(manifests, untrusted, logger)
        if not stale:
            return
        tag = f'cleanup_{reason}'
        namelist = os.path.join(passes_dir, f'{tag}.complist.txt')
        try:
            write_namelist(namelist, stale)
        except UnicodeEncodeError:
            logger.warning('component names are not ASCII - skipping cleanup')
            return
        checkpoint_scene(scene, checkpoints_dir, tag, logger)
        logger.info('--- cleanup (%s): deleting %s ---', reason, stale)
        result = run_pass(tag, 'cleanup', payload=namelist)
        entry = {'tag': tag, 'mode': 'cleanup', 'stale': stale,
                 'workflow_success': result.success,
                 'errors': result.errors,
                 'duration_seconds': round(result.duration_seconds, 1)}
        if result.success:
            for name in stale:
                dropped = manifests.pop(name, None)
                if dropped is not None:
                    dropped.setdefault('history', []).append(
                        new_history_entry('dropped_stale', reason=reason))
            entry['accepted'] = True
        else:
            restore_scene(scene, checkpoints_dir, tag, logger)
            entry['accepted'] = False
            entry['rolled_back'] = True
            logger.warning('cleanup failed and was rolled back - components '
                           'left in place (duplicates are tolerated by design)')
        prune_checkpoints(checkpoints_dir, {'initial', tag}, logger)
        record(entry)

    # ------------------------------------------------------------------
    # 2. Global re-align, all images enabled, accept/rollback
    # ------------------------------------------------------------------
    if not args.skip_global:
        tag = 'global'
        export_dir = os.path.join(passes_dir, tag)
        checkpoint_scene(scene, checkpoints_dir, tag, logger)
        logger.info('--- stage 2: global re-align (all images enabled) ---')
        result = run_pass(tag, 'global', export_dir=export_dir)
        after = take_census(images_root, stem_index, logger)
        accepted, lost = evaluate(tag, baseline, after, result.success)
        entry = {'tag': tag, 'mode': 'global',
                 'workflow_success': result.success, 'errors': result.errors,
                 'registered_before': len(baseline),
                 'registered_after': len(after),
                 'gain': len(after) - len(baseline),
                 'lost_images': len(lost), 'accepted': accepted,
                 'duration_seconds': round(result.duration_seconds, 1)}
        if accepted:
            baseline = after
            note_exports(export_dir)
            # Refresh per-component composition from this full export.
            if try_build_manifests(export_dir, zone, logger):
                pass
            fresh = load_contract_manifests(export_dir, logger)
            if fresh:
                manifests = fresh
                untrusted.clear()
            elif manifests:
                logger.warning('global pass accepted but manifests could '
                               'not be refreshed - per-component data is '
                               'now approximate')
                untrusted.update(manifests)
        else:
            restore_scene(scene, checkpoints_dir, tag, logger)
            entry['rolled_back'] = True
        prune_checkpoints(checkpoints_dir, {'initial', tag}, logger)
        record(entry)
        cleanup_stale('post_global')

    # ------------------------------------------------------------------
    # 3. Rigid -mergeComponents consolidation (cannot shrink)
    # ------------------------------------------------------------------
    tag = 'merge'
    checkpoint_scene(scene, checkpoints_dir, tag, logger)
    logger.info('--- stage 3: rigid mergeComponents consolidation ---')
    result = run_pass(tag, 'merge')
    entry = {'tag': tag, 'mode': 'merge',
             'workflow_success': result.success, 'errors': result.errors,
             'accepted': result.success,
             'duration_seconds': round(result.duration_seconds, 1)}
    if result.success:
        # Rigid merge adds no images and cannot shrink; the merged
        # component only becomes enumerable at the next align export
        # (exportLatestComponents does not cover plain merges), so the
        # per-component picture is approximate until then.
        if manifests:
            untrusted.update(manifests)
    else:
        restore_scene(scene, checkpoints_dir, tag, logger)
        entry['rolled_back'] = True
    prune_checkpoints(checkpoints_dir, {'initial', tag}, logger)
    record(entry)

    # ------------------------------------------------------------------
    # 4. Per-component growth loop, largest first, while gains > 0
    # ------------------------------------------------------------------
    passes_used = 0
    sweep = 0
    if not manifests:
        logger.warning('stage 4 skipped: no component manifests')
    while manifests and passes_used < max_passes:
        sweep += 1
        sweep_gain = 0
        order = sorted(
            manifests,
            key=lambda n: manifests[n].get('camera_count', len(manifests[n]['images'])),
            reverse=True)
        logger.info('--- stage 4 sweep %d: %d components, largest first ---',
                    sweep, len(order))
        for name in order:
            if passes_used >= max_passes:
                logger.info('max_passes (%d) reached', max_passes)
                break
            if name not in manifests:
                continue  # dropped by a cleanup earlier in this sweep
            # Orphans from the ZONE census, not the manifests: growth
            # passes are align-UPDATES that refresh every component, and
            # post-pass manifests may be approximate (2026-07-24 fix for
            # phantom gains).
            orphans = set(all_basenames) - baseline
            if not orphans:
                logger.info('no orphan images remain - nothing left to grow from')
                break
            m = manifests[name]
            passes_used += 1
            safe = re.sub(r'[^A-Za-z0-9._-]', '_', name)
            tag = f'grow_s{sweep}_{safe}'
            export_dir = os.path.join(passes_dir, tag)
            primary_list = os.path.join(passes_dir, f'{tag}_primary.imagelist')
            secondary_list = os.path.join(passes_dir, f'{tag}_orphans.imagelist')
            try:
                n_primary = write_imagelist(primary_list, set(m['images']),
                                            basename_index, logger)
                n_secondary = write_imagelist(secondary_list, orphans,
                                              basename_index, logger)
            except (ValueError, UnicodeEncodeError) as exc:
                logger.warning('skipping component "%s": %s', name, exc)
                continue

            checkpoint_scene(scene, checkpoints_dir, tag, logger)
            logger.info('--- grow pass %d/%d: "%s" (%d images + %d orphans, '
                        'featureSource %d) ---', passes_used, max_passes,
                        name, n_primary, n_secondary, feature_source)
            result = run_pass(tag, 'component', payload=primary_list,
                              fsource=str(feature_source),
                              export_dir=export_dir,
                              secondary=secondary_list)
            # ZONE-LEVEL accounting (2026-07-24): -align with components
            # present is an UPDATE that refreshes every component in the
            # scene, so the census after an "isolated" pass covers the
            # WHOLE zone. Comparing it against one component's membership
            # produced phantom gains (observed: "sweep gain 1856" on a
            # 976-image zone). The invariant and the gain are therefore
            # evaluated against the zone baseline census.
            after = take_census(images_root, stem_index, logger)
            before = set(baseline)
            accepted, lost = evaluate(tag, before, after, result.success)
            gain = len(after) - len(before)
            entry = {'tag': tag, 'mode': 'component', 'component': name,
                     'workflow_success': result.success, 'errors': result.errors,
                     'enabled_primary': n_primary, 'enabled_orphans': n_secondary,
                     'registered_before': len(before),
                     'registered_after': len(after),
                     'gain': gain, 'lost_images': len(lost),
                     'accepted': accepted,
                     'duration_seconds': round(result.duration_seconds, 1)}
            if accepted:
                sweep_gain += max(gain, 0)
                note_exports(export_dir)
                if try_build_manifests(export_dir, zone, logger):
                    pass
                fresh = load_contract_manifests(export_dir, logger)
                if fresh:
                    # Authoritative composition for the components this
                    # alignment produced.
                    for fname, fm in fresh.items():
                        manifests[fname] = fm
                        untrusted.discard(fname)
                else:
                    # No fresh manifests: keep the PRE-PASS membership
                    # (approximate but never inflated - assigning the
                    # whole zone census to one component previously
                    # poisoned orphan/gain accounting) and flag it so
                    # cleanup can never act on it.
                    m.setdefault('history', []).append(new_history_entry(
                        'grow_pass_accepted', tag=tag, gain=gain,
                        approximate=True))
                    untrusted.add(name)
                    if len(exported_components(export_dir)) > 1:
                        logger.warning('pass %s produced multiple components; '
                                       'manifest for "%s" is approximate', tag, name)
                baseline = set(after)
            else:
                restore_scene(scene, checkpoints_dir, tag, logger)
                entry['rolled_back'] = True
            prune_checkpoints(checkpoints_dir, {'initial', tag}, logger)
            record(entry)
            if accepted:
                cleanup_stale(tag)
        if sweep_gain == 0:
            logger.info('sweep %d gained nothing - growth converged', sweep)
            break
        logger.info('sweep %d total gain: %d cameras', sweep, sweep_gain)

    # ------------------------------------------------------------------
    # 5. Final export + manifests + report
    # ------------------------------------------------------------------
    final_dir = os.path.join(output_dir, 'final_components')
    os.makedirs(final_dir, exist_ok=True)
    logger.info('--- stage 5: final component export ---')
    result = run_pass('final', 'export', export_dir=final_dir)
    final_entry = {'tag': 'final', 'mode': 'export',
                   'workflow_success': result.success, 'errors': result.errors,
                   'duration_seconds': round(result.duration_seconds, 1)}
    if result.success:
        note_exports(final_dir)
        final_census = take_census(images_root, stem_index, logger)
        if final_census:
            final_entry['registered'] = len(final_census)
            baseline |= final_census
        try_build_manifests(final_dir, zone, logger)
    record(final_entry)

    # Component table: every tracked component at its LATEST export
    # location (never copied elsewhere - a relocated .rsalign hangs
    # -importComponent, hard rule 7). exportLatestComponents only covers
    # the last alignment, so earlier pass exports remain authoritative
    # for components that alignment did not touch.
    final_components = {}
    for name, m in manifests.items():
        rsalign = last_export.get(name)
        m['rsalign'] = rsalign or m.get('rsalign')
        m.setdefault('history', []).append(new_history_entry('grow_stage_final'))
        if rsalign:
            write_manifest(m, os.path.dirname(rsalign))
        final_components[name] = {
            'rsalign': m.get('rsalign'),
            'camera_count': m.get('camera_count'),
            'approximate': name in untrusted,
        }
    for name, path in last_export.items():
        if name not in final_components:
            final_components[name] = {'rsalign': path, 'camera_count': None,
                                      'approximate': True}

    registered = len(baseline)
    report['final'] = {
        'registered_images': registered,
        'registered_fraction': round(registered / len(all_basenames), 4),
        'orphans_remaining': len(compute_orphans(manifests, all_basenames, logger))
        if manifests else None,
        'component_passes_used': passes_used,
        'components': final_components,
    }
    save_report()
    logger.info('grow complete: %d/%d unique images registered (%.1f%%); '
                'report: %s', registered, len(all_basenames),
                100.0 * registered / len(all_basenames), report_path)
    logger.info('Next: cross-zone merge (merge_zones.py) over the final '
                'component exports listed in the report')
    return 0


if __name__ == '__main__':
    sys.exit(main())
