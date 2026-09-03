#!/usr/bin/env python3
"""
Decimate every component's mesh to a triangle budget, re-bake its texture at
adaptive 4K, and export an OBJ.

WHY THIS EXISTS
---------------
`GenerateModel.bat` finishes a component with FOUR relative 80% simplify
passes. 0.8^4 = 41%, which on NA165/H2060 left the "Simplified" models at
2.8-42 M triangles - deliverable-sized for nothing. Reaching a real budget
needs a pass count that depends on where the mesh STARTED, so it has to be
measured, not hard-coded.

MEASUREMENT PRIMITIVE
---------------------
`-exportReport <out> "<install>\\Reports\\SelectedModel.html"` renders
`$(modelTriangleCount)` for whatever `-selectModel` last selected. Probed
2026-09-03 on the 119 GB H2060 master: ~4 s, headless, non-blocking. Before
this, model size could only be guessed from `.dat` byte counts.

WHY EVERY SELECT IS VERIFIED  <-- the reason this is Python and not a .bat
--------------------------------------------------------------------------
`-selectModel <name-that-does-not-exist>` is a **silent no-op**: the previous
selection stays active and `lastError` stays `0`. Proven 2026-09-03 against a
loaded component - selecting "zone_all_c15_THIS_DOES_NOT_EXIST" left
`zone_all_c15_Simplified_Textured` selected and reported no error.

So `-selectModel X` followed by `-deleteSelectedModel` does not delete X when X
is absent - it deletes whatever was selected before. The first version of this
tool used that pattern to drop simplification intermediates and destroyed its
own working model three passes in. Here, `select()` re-reads the model name out
of a report and returns False on mismatch, and `delete()` refuses to act unless
the select verified. Never call a destructive operation after an unverified
select.

VERIFY BY CENSUS, NEVER BY EXIT STATUS
--------------------------------------
A component counts as done only when its OBJ exists on disk AND a fresh
measurement of the exported model is at or under budget.
"""

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time

DEFAULT_BUDGET = 500_000
# Relative target of SimplifySmooth_80per_Params.xml: each pass KEEPS this
# fraction. Measured on H2060, -cleanModel removes essentially nothing on top
# (every component's Simplified/HighPoly ratio came out at 0.4096 = 0.8^4 to
# four decimals), so the geometric model predicts the pass count reliably.
PASS_RATIO = 0.80
MIN_FREE_GB = 40

HERE = os.path.dirname(os.path.abspath(__file__))
META = os.path.join(HERE, 'modules', 'realityscan_interface', 'RS_CLI', 'Metadata')


def rs_exe():
    env = os.environ.get('RS_EXECUTABLE')
    if env and os.path.exists(env):
        return env
    for p in (r"C:\Program Files\Epic Games\RealityScan_2.2\RealityScan.exe",
              r"C:\Program Files\Epic Games\RealityScan_2.1\RealityScan.exe",
              r"C:\Program Files\Epic Games\RealityScan_2.0\RealityScan.exe"):
        if os.path.exists(p):
            return p
    raise SystemExit("RealityScan.exe not found - set RS_EXECUTABLE")


def free_gb(path):
    drive = os.path.splitdrive(os.path.abspath(path))[0] + os.sep
    return shutil.disk_usage(drive).free / 2**30


class Rs:
    """One loaded RealityScan instance, driven by delegation."""

    def __init__(self, exe, name, work):
        self.exe, self.name = exe, name
        self.work = work
        self.template = os.path.join(os.path.dirname(exe), 'Reports', 'SelectedModel.html')
        os.makedirs(work, exist_ok=True)

    def _raw(self, args, timeout):
        return subprocess.run([self.exe, *args], capture_output=True, text=True,
                              timeout=timeout)

    def status(self):
        r = self._raw(['-getStatus', self.name], 120)
        return r.stdout.strip() if r.returncode == 0 else None

    def alive(self):
        return self.status() is not None

    def cmd(self, *args, timeout=24 * 3600):
        """Delegate one command and wait for it. Double wait: -waitCompleted can
        return before the instance has picked the command up."""
        self._raw(['-delegateTo', self.name, *args], timeout)
        self._raw(['-waitCompleted', self.name], timeout)
        time.sleep(1)
        self._raw(['-waitCompleted', self.name], timeout)

    # ---------------------------------------------------------------- report
    def report(self):
        """(model_name, triangle_count) of the current selection, or (None, None)."""
        out = os.path.join(self.work, 'measure.html')
        try:
            if os.path.exists(out):
                os.remove(out)
        except OSError:
            pass
        self.cmd('-exportReport', out, self.template, timeout=1800)
        if not os.path.exists(out) or os.path.getsize(out) == 0:
            return None, None
        with open(out, encoding='utf-8', errors='replace') as fh:
            html = fh.read()
        # Label and value sit on consecutive lines; anchor on the label.
        nm = re.search(r"<th>Model name</th>\s*<td>([^<]*)</td>", html)
        tr = re.search(r"Triangles' count</th>\s*<td>(\d+)</td>", html)
        return (nm.group(1).strip() if nm else None,
                int(tr.group(1)) if tr else None)

    # ---------------------------------------------------------------- select
    def select(self, model):
        """Select `model` and PROVE it. False if the model is absent."""
        self.cmd('-selectModel', model, timeout=1800)
        nm, _ = self.report()
        return nm == model

    def measure(self, model):
        """Triangle count of `model`, or None if absent/unmeasurable."""
        self.cmd('-selectModel', model, timeout=1800)
        nm, tr = self.report()
        return tr if nm == model else None

    def rename(self, new):
        """Rename the current selection and prove the new name took."""
        self.cmd('-renameSelectedModel', new, timeout=1800)
        nm, _ = self.report()
        return nm == new

    def delete(self, model):
        """Delete `model` only if a verified select found it. Never blind."""
        if not self.select(model):
            return False
        self.cmd('-deleteSelectedModel', timeout=1800)
        return True


def passes_for(tris, budget):
    if tris is None or tris <= budget:
        return 0
    return max(1, math.ceil(math.log(budget / tris) / math.log(PASS_RATIO)))


def decimate(rs, comp, seed_suffix, budget, export_dir, log):
    """Run one component. Returns a result dict."""
    rec = {'component': comp}
    t0 = time.time()
    obj = os.path.join(export_dir, f'{comp}.obj')

    tex = os.path.join(META, 'Texturing_AdaptiveTexel_4k.xml')
    unwrap = os.path.join(META, 'Unwrapping_AdaptiveTexel_4k.xml')
    simplify = os.path.join(META, 'SimplifySmooth_80per_Params.xml')
    reproj = os.path.join(META, 'ReprojectionParams.xml')
    # METRIC, not the stock OBJ preset. ModelExportParamsObj.xml carries
    # MvsExportScale{X,Y,Z}=100 and the Unreal transformation preset, which is
    # right for a game engine and wrong for survey: it would put these OBJs at
    # 100x the scale of every deliverable already shipped for this dive (the
    # H2060 exports used ModelExportParamsOBJ_NiraParts.xml, scale 1.0). The
    # metric variant is scale 1.0 and writes jpg for BOTH the colour and normal
    # layers, which is what was asked for.
    export = os.path.join(META, 'ModelExportParamsObj_Metric.xml')
    for f in (tex, unwrap, simplify, reproj, export):
        if not os.path.exists(f):
            return dict(rec, status='fail', why=f'missing parameter file {f}')

    rs.cmd('-selectComponent', comp, timeout=1800)

    # 1. Re-texture the high-poly IN PLACE - "the original high-poly textured
    #    model, run it again" (owner, 2026-09-03). It is deliberately NOT
    #    renamed: -calculateTexture edits the model rather than producing a new
    #    one, so renaming would consume the stable identifier and leave a re-run
    #    unable to find its own source.
    #
    #    `_HighPoly_Textured` is the source of record; `_HighPoly_Raw` is only a
    #    fallback. They are not interchangeable - on H2060 the raw mesh carried
    #    MORE triangles than the textured one (c15: 9,706,654 vs 6,767,368),
    #    because texturing applies the unwrap's large-triangle removal.
    hp = f'{comp}_HighPoly_Textured'
    if not rs.select(hp):
        hp = f'{comp}_HighPoly_Raw'
        if not rs.select(hp):
            return dict(rec, status='fail',
                        why=f'neither {comp}_HighPoly_Textured nor _HighPoly_Raw found')
    rec['texture_source'] = hp
    log(f'    [1/5] texturing {hp} at adaptive 4K')
    rs.cmd('-calculateTexture', tex)

    # 2. Decimate.
    seed = f'{comp}_{seed_suffix}'
    start = rs.measure(seed)
    if start is None:
        return dict(rec, status='fail', why=f'could not measure seed {seed}')
    n = passes_for(start, budget)
    rec.update(start_triangles=start, passes=n)
    log(f'    [2/5] decimating {seed}: {start:,} tris -> {n} pass(es), '
        f'predicted {int(start * PASS_RATIO ** n):,}')
    if not rs.select(seed):
        return dict(rec, status='fail', why=f'{seed} vanished before decimation')

    prev = None
    for i in range(1, n + 1):
        rs.cmd('-simplify', simplify)
        if not rs.rename(f'{comp}_Dec{i}'):
            return dict(rec, status='fail', why=f'rename after simplify pass {i} failed')
        rs.cmd('-cleanModel')
        if not rs.rename(f'{comp}_DecC{i}'):
            return dict(rec, status='fail', why=f'rename after clean pass {i} failed')
        # Drop this pass's pre-clean model and the previous pass's survivor, so
        # at most two intermediates are resident. Both deletes are verified, so
        # an already-absent name (if -cleanModel edits in place) is a safe skip.
        rs.delete(f'{comp}_Dec{i}')
        if prev:
            rs.delete(prev)
        prev = f'{comp}_DecC{i}'
        if not rs.select(prev):
            return dict(rec, status='fail', why=f'lost {prev} after pass {i}')
        if i == n or i % 5 == 0:
            _, got = rs.report()
            log(f'      pass {i}/{n}: {got:,} tris')

    final = f'{comp}_Dec500k'
    if prev is None:
        # Already inside budget: clean once so the exported model is still
        # cleaned, and carry it forward under the deliverable name.
        if not rs.select(seed):
            return dict(rec, status='fail', why=f'{seed} vanished')
        rs.cmd('-cleanModel')
    if not rs.rename(final):
        return dict(rec, status='fail', why='could not rename final model')

    # 3/4. Unwrap then bake the high-poly texture onto the decimated mesh.
    log('    [3/5] unwrapping at adaptive 4K')
    rs.cmd('-unwrap', unwrap)
    log(f'    [4/5] reprojecting {hp} -> {final}')
    rs.cmd('-reprojectTexture', hp, final, reproj)
    # -reprojectTexture does not document which of source/result it leaves
    # selected, so re-select the target explicitly before exporting.
    if not rs.select(final):
        return dict(rec, status='fail', why=f'lost {final} after reprojection')

    # 5. Export.
    log(f'    [5/5] exporting {comp}.obj')
    rs.cmd('-exportSelectedModel', obj, export)

    got = rs.measure(final)
    has_obj = os.path.exists(obj) and os.path.getsize(obj) > 0
    rec.update(triangles=got, obj=has_obj,
               obj_bytes=os.path.getsize(obj) if has_obj else 0,
               minutes=round((time.time() - t0) / 60, 1))
    if not has_obj:
        return dict(rec, status='fail', why='no OBJ written')
    if got is None:
        return dict(rec, status='fail', why='could not measure exported model')
    if got > budget:
        return dict(rec, status='fail', why=f'{got:,} tris still over budget')
    return dict(rec, status='ok')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--export-dir', required=True)
    ap.add_argument('--instance', default=os.environ.get('RS_INSTANCE', 'RS1'))
    ap.add_argument('--budget', type=int, default=DEFAULT_BUDGET)
    ap.add_argument('--components', default='')
    ap.add_argument('--seed-suffix', default='Simplified_Textured')
    ap.add_argument('--report', default='')
    ap.add_argument('--save-every', type=int, default=1)
    ap.add_argument('--crs', default=os.environ.get('RS_PROJECT_CRS', ''),
                    help='output coordinate system to pin, e.g. epsg:32702. A project '
                         'accumulates a LIST of coordinate systems across cruises and the '
                         'export writes whichever is selected - H2060 exports were labelled '
                         'epsg:32655 (UTM 55N), a leftover, because nothing pinned it.')
    ap.add_argument('--no-flush-cache', action='store_true',
                    help='do not -clearCache between components. Leave this OFF: the '
                         'cache grew ~8 GB per component on H2060 and took C: from 98 GB '
                         'to 28.5 GB in four components, tripping the disk floor.')
    ap.add_argument('--keep-stale', action='store_true',
                    help='do not delete the superseded *_Simplified_Textured / '
                         '*_HighPoly_Textured models after a verified export')
    args = ap.parse_args()

    exe = rs_exe()
    os.makedirs(args.export_dir, exist_ok=True)
    root = os.path.dirname(os.path.abspath(args.export_dir))
    rs = Rs(exe, args.instance, os.path.join(root, '_decimate_work'))
    if not rs.alive():
        raise SystemExit(f"instance {args.instance} unreachable - boot it and -load "
                         f"the project first (this script never resets a scene)")

    # Pin the OUTPUT scope before any export. ExportDeliverables.bat already
    # does this; run_decimate.py must too, or the .rsInfo inherits an arbitrary
    # entry from the project's coordinate-system list.
    if args.crs:
        rs.cmd('-setOutputCoordinateSystem', args.crs)
        print(f'output coordinate system pinned to {args.crs}', flush=True)
    else:
        print('WARNING: no --crs given; the export will label itself with whichever '
              'coordinate system the project happens to have selected', flush=True)

    report_path = args.report or os.path.join(root, 'decimate_report.json')
    comps = ([c.strip() for c in args.components.split(',') if c.strip()]
             if args.components.strip() else [f'zone_all_c{i}' for i in range(20)])

    def log(msg):
        print(f'{time.strftime("%H:%M:%S")} {msg}', flush=True)

    results = []
    log(f'=== decimate {len(comps)} component(s) to <= {args.budget:,} triangles ===')

    for idx, comp in enumerate(comps, 1):
        if not rs.alive():
            log(f'[{idx}/{len(comps)}] {comp}: INSTANCE VANISHED - stopping')
            results.append({'component': comp, 'status': 'abort', 'why': 'instance vanished'})
            break
        gb = free_gb(args.export_dir)
        if gb < MIN_FREE_GB:
            log(f'[{idx}/{len(comps)}] {comp}: DISK FLOOR {gb:.1f} GB - stopping')
            results.append({'component': comp, 'status': 'abort',
                            'why': f'only {gb:.1f} GB free'})
            break

        obj = os.path.join(args.export_dir, f'{comp}.obj')
        if os.path.exists(obj) and os.path.getsize(obj) > 0:
            got = rs.measure(f'{comp}_Dec500k')
            if got is not None and got <= args.budget:
                log(f'[{idx}/{len(comps)}] {comp}: already done ({got:,} tris)')
                results.append({'component': comp, 'status': 'skip', 'triangles': got})
                continue

        log(f'[{idx}/{len(comps)}] {comp} ({gb:.0f} GB free)')
        try:
            rec = decimate(rs, comp, args.seed_suffix, args.budget, args.export_dir, log)
        except subprocess.TimeoutExpired as exc:
            rec = {'component': comp, 'status': 'fail', 'why': f'timeout: {exc}'}
        results.append(rec)
        if rec['status'] == 'ok':
            log(f"    OK {rec['triangles']:,} tris, "
                f"{rec['obj_bytes'] / 2**20:.0f} MB OBJ, {rec['minutes']} min")
            if not args.keep_stale:
                # Only the superseded low-poly is stale. The high-poly was
                # re-textured in place at 4K and is the reprojection source of
                # record - deleting it would throw away the very thing the new
                # bake came from.
                rec['stale_deleted'] = rs.delete(f'{comp}_Simplified_Textured')
        else:
            log(f"    FAIL: {rec.get('why')}")

        if args.save_every and idx % args.save_every == 0:
            rs.cmd('-save')
            log('    project saved')

        # Flush the cache between components. RealityScan PERSISTS
        # appCacheCustomLocation across instances, so the cache may not be where
        # this boot put it - measure free space rather than a directory.
        # -clearCache was unreliable during MODELLING (148 GB -> 90.6 GB once);
        # for this texture/simplify workload it took 62 GB -> 5.5 MB, so it is
        # used here but still verified rather than trusted.
        if not args.no_flush_cache:
            before = free_gb(args.export_dir)
            rs.cmd('-clearCache', timeout=3600)
            after = free_gb(args.export_dir)
            log(f'    cache flush: {before:.0f} -> {after:.0f} GB free '
                f'({after - before:+.0f} GB)')
            if after < MIN_FREE_GB:
                log(f'    WARNING: still under the {MIN_FREE_GB} GB floor after a '
                    f'flush - the next component will abort')
        with open(report_path, 'w', encoding='utf-8') as fh:
            json.dump({'budget': args.budget, 'models': results}, fh, indent=2)

    rs.cmd('-save')
    with open(report_path, 'w', encoding='utf-8') as fh:
        json.dump({'budget': args.budget, 'crs': args.crs, 'models': results}, fh, indent=2)

    ok = [r for r in results if r.get('status') in ('ok', 'skip')]
    log(f'=== {len(ok)}/{len(comps)} at or under {args.budget:,} triangles ===')
    for r in results:
        if r.get('status') not in ('ok', 'skip'):
            log(f"  {r['component']}: {r.get('status')} - {r.get('why', '')}")
    log(f'report: {report_path}')
    return 0 if len(ok) == len(comps) else 1


if __name__ == '__main__':
    sys.exit(main())
