#!/usr/bin/env python3
"""Which components still need exporting - judged from disk, never from an exit code.

WHY THIS EXISTS (ported from NA165/H2060 _agent/export/remaining.py,
2026-09-14). ExportDeliverables.bat takes a multi-component name list and
loads the project ONCE (the load is the expensive part), but its :run
subroutine treats any non-empty errors file as fatal and jumps to :fail. One
bad component therefore kills every component after it in the list, and the
run exits 1 having silently skipped the remainder - on a 39-component
assembly, a whole-day loss for a single-component fault.

So a driver loops: export what is left, and if the batch dies, recompute what
is left FROM WHAT IS ON DISK and go again. Disk is the only honest ledger.

"Done" means every expected artefact for the pass is present and NON-EMPTY:

    meshes  for EVERY part index N found in obj/: <stem>_N.obj, <stem>_N.mtl
            and <stem>_N.obj.rsInfo; and fbx/ holds exactly the same part
            indices, each with <stem>_N.fbx and <stem>_N.fbx.rsInfo
    ply     every ply/<stem>_dense*.ply (at least one) with its .ply.rsInfo

PART INDICES, NOT AN EXACT NAME: ExportDeliverables exports BY PARTS and
RealityScan names a part with a seven-digit index (zone_1_c40_0000000.obj,
not zone_1_c40.obj). The first version checked the exact stem, matched
nothing, and reported every finished component as still to do. The .rsInfo
sidecars are the per-PART completion markers: RealityScan writes one as each
part finishes, not once at the end (NA165 zone_1_c42: 0000000.fbx.rsInfo and
0000001.fbx.rsInfo at 01:11:20, 0000002.fbx created at 01:11:33). So "at
least one file per pattern" called an export interrupted after part 1 done
(review 2026-09-27); the part sets are compared instead - on all 39 NA165
components they are identical across obj/mtl/obj.rsInfo/fbx/fbx.rsInfo. The
FBX runs AFTER the OBJ, so a complete FBX set also means the OBJ finished.
The .mtl is required, not cosmetic: a textured OBJ without its material file
is an untextured OBJ to every consumer.

Names are matched with os.listdir and re.escape, never glob: a '[' in a
component name or export path is a glob character class, and a finished
component would read "to do" forever.

With --textures jpg the textures are part of "done": every map_* in every MTL
must name a .jpg that exists, is non-empty and starts FF D8 FF, and the same
file must be in fbx/. A preset key RealityScan ignores fails SILENTLY (the
export succeeds and writes PNG), so this is the only place it is caught.

<stem> = <component><suffix>: the component is SELECTED by its existing name
and WRITTEN under the suffixed one (RS_EXPORT_SUFFIX, e.g. _L).

Usage:
    python -m modules.export_remaining --exports <dir> --out <listfile>
        (--names <list> | --report <models_report.json>)
        [--suffix _L] [--pass meshes|ply] [--textures png|jpg]

Exit 0 with a populated list file, 3 when nothing remains (the caller reads
3 as "pass complete", distinct from an error), 2 on bad input or when the
list cannot be written (the previous list is then left as it was - it is
replaced atomically, never truncated first). --help exits 0 and writes
nothing; a driver never passes it. --textures png is accepted and verifies
nothing beyond the meshes (PNG is what a default export writes).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from modules.export_deliverables import (SUFFIX_RE, TEXTURE_FORMATS,  # noqa: E402
                                         read_component_names)

PASSES = ('meshes', 'ply')
JPEG_MAGIC = b'\xff\xd8\xff'


def _listing(directory: str) -> set[str]:
    try:
        return set(os.listdir(directory))
    except OSError:
        return set()


def _nonempty(directory: str, name: str) -> bool:
    try:
        return os.path.getsize(os.path.join(directory, name)) > 0
    except OSError:
        return False


def part_indices(directory: str, stem: str, ext: str) -> set[str]:
    """The seven-digit part indices N of every <stem>_N.<ext> in directory."""
    pat = re.compile(re.escape(stem) + r'_(\d{7})\.' + re.escape(ext) + r'\Z',
                     re.IGNORECASE)
    return {m.group(1) for m in map(pat.match, _listing(directory)) if m}


def mtl_texture_names(obj_dir: str, stem: str) -> list[str]:
    """Every map_* target named by the component's MTL files, in order."""
    names: list[str] = []
    for index in sorted(part_indices(obj_dir, stem, 'mtl')):
        mtl = os.path.join(obj_dir, f'{stem}_{index}.mtl')
        with open(mtl, encoding='utf-8', errors='replace') as fh:
            for line in fh:
                token = line.strip().split()
                if len(token) >= 2 and token[0].lower().startswith('map_'):
                    names.append(token[-1])
    return names


def texture_problems(exports_dir: str, component: str, suffix: str,
                     textures: str) -> list[str]:
    """Why this component's textures are not in ``textures`` format ([] = fine)."""
    if textures != 'jpg':
        return []
    stem = component + suffix
    obj_dir = os.path.join(exports_dir, stem, 'obj')
    fbx_dir = os.path.join(exports_dir, stem, 'fbx')
    refs = mtl_texture_names(obj_dir, stem)
    if not refs:
        return [f'{stem}: no map_* reference in any MTL']
    problems = []
    for ref in refs:
        if not ref.lower().endswith(('.jpg', '.jpeg')):
            problems.append(f'{stem}: MTL references {ref}')
            continue
        for where in (obj_dir, fbx_dir):
            path = os.path.join(where, ref)
            try:
                with open(path, 'rb') as fh:
                    head = fh.read(3)
            except OSError:
                problems.append(f'{stem}: {os.path.basename(where)}/{ref} missing')
                continue
            if head != JPEG_MAGIC:
                problems.append(f'{stem}: {os.path.basename(where)}/{ref} is not '
                                'a JPEG (no FF D8 FF)')
    return problems


def component_done(exports_dir: str, component: str, pass_: str = 'meshes',
                   suffix: str = '', textures: str | None = None) -> bool:
    """Has this component's artefacts for this pass, complete and non-empty?"""
    stem = component + suffix
    base = os.path.join(exports_dir, stem)
    if pass_ == 'ply':
        ply_dir = os.path.join(base, 'ply')
        pat = re.compile(re.escape(stem) + r'_dense.*\.ply\Z', re.IGNORECASE)
        plys = [n for n in _listing(ply_dir) if pat.match(n)]
        return bool(plys) and all(_nonempty(ply_dir, n) and _nonempty(ply_dir, n + '.rsInfo')
                                  for n in plys)
    obj_dir, fbx_dir = os.path.join(base, 'obj'), os.path.join(base, 'fbx')
    parts = part_indices(obj_dir, stem, 'obj')
    if not parts or part_indices(fbx_dir, stem, 'fbx') != parts:
        return False
    for n in parts:
        part = f'{stem}_{n}'
        if not all(_nonempty(obj_dir, part + ext) for ext in ('.obj', '.mtl', '.obj.rsInfo')):
            return False
        if not all(_nonempty(fbx_dir, part + ext) for ext in ('.fbx', '.fbx.rsInfo')):
            return False
    if textures:
        return not texture_problems(exports_dir, component, suffix, textures)
    return True


def components_from_report(report_path: str) -> list[str]:
    """Successful models from a models_report.json, SMALLEST FIRST - the same
    cost ladder run_models uses: a cheap component that fails fails early."""
    with open(report_path, encoding='utf-8') as fh:
        report = json.load(fh)
    models = [m for m in report['models'] if m.get('success')]
    models.sort(key=lambda m: m.get('cameras', 0))
    return [m['component'] for m in models]


def write_list(path: str, names: list[str]) -> None:
    """CRLF, ASCII: the .bat reads it with `for /f "usebackq delims="`, which
    keeps a trailing CR as part of the name if the file is written LF-only.

    Encoded first and swapped in with os.replace, so a name the list cannot
    hold (non-ASCII) or a failed write leaves the previous list whole instead
    of truncated to a prefix the driver would then export."""
    data = ''.join(name + '\r\n' for name in names).encode('ascii')
    tmp = path + '.tmp'
    with open(tmp, 'wb') as fh:
        fh.write(data)
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--exports', required=True, help='export tree root')
    ap.add_argument('--out', required=True, help='list file to (re)write')
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument('--names', help='component list, one name per line')
    src.add_argument('--report', help='models_report.json (successful models, '
                                      'smallest first)')
    ap.add_argument('--suffix', default='', help='output stem suffix, e.g. _L')
    ap.add_argument('--pass', dest='pass_', default='meshes', choices=PASSES)
    ap.add_argument('--textures', default=None, choices=TEXTURE_FORMATS,
                    help='also require every MTL-referenced texture in this '
                         'format (meshes pass only)')
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    if not SUFFIX_RE.match(args.suffix):
        print(f'ERROR: suffix {args.suffix!r} - letters, digits, _ and - only')
        return 2
    try:
        comps = (components_from_report(args.report) if args.report
                 else read_component_names(args.names))
    except (OSError, ValueError, KeyError) as exc:
        print(f'ERROR: cannot read the component source: {exc}')
        return 2
    if not comps:
        print('ERROR: the component source names nothing')
        return 2

    textures = args.textures if args.pass_ == 'meshes' else None
    todo = [c for c in comps
            if not component_done(args.exports, c, args.pass_, args.suffix, textures)]
    try:
        write_list(args.out, todo)
    except (OSError, UnicodeEncodeError) as exc:
        print(f'ERROR: cannot write the list {args.out!r}: {exc}')
        return 2

    print('pass=%s done=%d' % (args.pass_, len(comps) - len(todo)))
    # On its OWN line, one `=`, nothing else: the caller parses this with
    # `for /f "tokens=2 delims=="` to detect an attempt that made no progress.
    print('REMAINING=%d' % len(todo))
    if todo:
        print('next: ' + ', '.join(todo[:5]) + ('...' if len(todo) > 5 else ''))
        return 0
    return 3


if __name__ == '__main__':
    sys.exit(main())
