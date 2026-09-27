#!/usr/bin/env python3
"""Export the per-component deliverables of a finished, modelled assembly.

Thin driver over ``ExportDeliverables.bat``, which does the real work in
ONE RealityScan session (per component named in the list file:
OBJ_NiraParts, FBX_Parts, dense colored PLY). The deliverable pinning
lives entirely in the .bat and its Metadata presets
(ModelExportParamsOBJ_NiraParts / ModelExportParamsFBX_Parts /
ModelExportParamsPLY_DensePoints) - this driver adds nothing to them.

It exists so the export stage goes through
``RealityScanCLI.run_batch_script`` like every other RealityScan
invocation (hard rule 1): per-instance lock, marker-file hygiene, progress
tailing and stall warnings, resource trace, and verified instance
shutdown. The wildscan portal previously ran the .bat via a raw
``["cmd", "/c", ...]`` Popen, which provided none of that, broke on
space-containing checkout paths (cmd strips the outer quotes -
run_batch_script's own comment), and - because the portal runner captures
stdout in a PIPE - let the ``start ""``-launched RealityScan GUI child
inherit that pipe (WINDOWS TRAP recorded 2026-08-07). run_batch_script
hands the .bat a log FILE instead, so the boot path stays detached.

Layering note: this module is imported by wildscan (and importable by any
driver) but imports only module_base + modules code itself - never
wildscan. The stage passes the workspace-derived paths as arguments.

Usage:
    py -3.13 modules/export_deliverables.py
        --project D:/dive/final_assembly/assembly/Assembly.rsproj
        --exports D:/dive/exports
        --names   D:/dive/exports/components.names
        [--log_dir D:/dive/logs] [--flight-log <log> | --crs epsg:NNNNN]
        [--suffix _L] [--textures png|jpg] [--no-save | --save]
        [--only all|meshes|ply]
        [--target-log <log> --target-params <FlightLogParams.xml>]
        [--registration-dir <dir>]
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from module_base.settings_store import SettingsStore, realityscan_env  # noqa: E402
from modules.flight_logs import crs_for_flight_log  # noqa: E402
from modules.realityscan_interface.realityscan_cli import (  # noqa: E402
    CMD_METACHARACTERS, RealityScanCLI)


# Per component, ExportDeliverables.bat writes one subfolder per format.
EXPORT_KINDS = ('obj', 'fbx', 'ply')

# RS_EXPORT_SUFFIX is expanded into every output path by the .bat, which
# refuses anything outside this set before booting (:charsOk). Checked here
# as well so the refusal costs nothing and names the remedy. \Z, not $: `$`
# also matches in front of a trailing newline, and '_L\n' passed.
SUFFIX_RE = re.compile(r'\A[A-Za-z0-9_-]*\Z')
# The .bat's path whitelist for RS_EXPORT_TARGET_LOG / _TARGET_PARAMS /
# _REGISTRATION_DIR (:charsOk path): no ( ) , ; = ~ and no cmd metacharacter.
PATH_RE = re.compile(r"\A[A-Za-z0-9_\-.\\:'+#@${}\[\] ]*\Z")
PATH_SWITCHES = ('RS_EXPORT_TARGET_LOG', 'RS_EXPORT_TARGET_PARAMS',
                 'RS_EXPORT_REGISTRATION_DIR')
TEXTURE_FORMATS = ('png', 'jpg')
# Line 2 of a registration CSV in the camera-poses format {...0A4A}
# (calibration.xml); line 1 is "#cameras N" in every RUMI format.
POSES_HEADER = '#name,lat,lon,alt,'


def export_suffix() -> str:
    """RS_EXPORT_SUFFIX exactly as ExportDeliverables.bat will apply it.

    The suffix goes on what is WRITTEN (folder and file stem), never on what
    is SELECTED: the component and its models keep their existing names in
    the project (zone_1_c0, zone_1_c0_Simplified_Textured), and the export
    lands as <exports>/zone_1_c0_L/obj/zone_1_c0_L_0000000.obj.
    """
    suffix = os.environ.get('RS_EXPORT_SUFFIX', '')
    if not SUFFIX_RE.match(suffix):
        raise ValueError(
            f'RS_EXPORT_SUFFIX={suffix!r}: only letters, digits, "_" and "-" '
            'are allowed - it is expanded into every output path, and '
            'ExportDeliverables.bat refuses anything else before boot.')
    return suffix


def export_stem(component: str, suffix: str | None = None) -> str:
    """Folder and file stem a component is exported under."""
    return component + (export_suffix() if suffix is None else suffix)


def expected_kinds() -> tuple[str, ...]:
    """The formats this run is actually supposed to produce.

    RS_EXPORT_SKIP_PLY makes ExportDeliverables.bat skip the dense PLY, whose
    source model (`<comp>_HighPoly_Raw` / `_HighPoly_Textured`) does not
    survive GenerateModel in this build. The census must agree with the
    workflow: without this it reported "1 of 3 expected deliverable folder(s)
    hold no file: <comp>/ply" and failed a run whose OBJ and FBX were both
    complete (NA165/H2060, 2026-09-01).

    RS_EXPORT_ONLY_PLY is the other half: a PLY-only pass must not be failed
    for the OBJ/FBX it was told not to write. Both together export nothing;
    the .bat refuses that before boot and so does this.

    Deliberately env-driven and narrow - the census keeps its teeth for every
    format the run DID ask for.
    """
    skip = os.environ.get('RS_EXPORT_SKIP_PLY')
    only = os.environ.get('RS_EXPORT_ONLY_PLY')
    if skip and only:
        raise ValueError('RS_EXPORT_SKIP_PLY and RS_EXPORT_ONLY_PLY are both '
                         'set - that exports nothing')
    if only:
        return ('ply',)
    if skip:
        return tuple(k for k in EXPORT_KINDS if k != 'ply')
    return EXPORT_KINDS


def unsafe_component_names(names: list[str]) -> list[str]:
    """Names the .bat would corrupt or execute.

    The list crosses as a FILE (hard rule 8), but each line then goes through
    `call :export_component "%%N"`, which re-parses it: '%' expands, '^' is
    doubled, '&' runs. assert_bat_safe guards arguments, not file lines.
    """
    return [n for n in names if set(n) & CMD_METACHARACTERS]


def read_component_names(names_file: str) -> list[str]:
    """Non-blank component names from the list file, BOM-tolerant."""
    with open(names_file, encoding='utf-8-sig') as fh:
        return [line.strip() for line in fh if line.strip()]


def missing_exports(exports_dir: str, names: list[str],
                    suffix: str | None = None) -> list[str]:
    """'<stem>/<kind>' entries that hold no non-empty file.

    The .bat's per-component loop runs zero iterations on an empty name
    list, falls through to -quit and exits 0; and a selection-driven
    export under -silent can auto-answer the "Export Selection" dialog and
    export NOTHING while still succeeding (MergeZoneComponents.bat records
    the census reading 0). Exit code plus an empty errors marker is
    therefore not evidence a deliverable exists (audit 2026-08-07).

    ``names`` are the SELECTED component names; the folders checked are
    their export stems (``suffix`` defaults to RS_EXPORT_SUFFIX, the value
    the .bat applied). Looking under the bare name after a suffixed export
    would report every component missing.
    """
    missing = []
    kinds = expected_kinds()
    for name in names:
        stem = export_stem(name, suffix)
        for kind in kinds:
            kind_dir = os.path.join(exports_dir, stem, kind)
            try:
                produced = any(
                    os.path.getsize(os.path.join(kind_dir, f)) > 0
                    for f in os.listdir(kind_dir)
                    if os.path.isfile(os.path.join(kind_dir, f)))
            except OSError:
                produced = False
            if not produced:
                missing.append(f'{stem}/{kind}')
    return missing


def apply_switches(args) -> None:
    """Carry the CLI switches to ExportDeliverables.bat as its environment.

    The .bat's contract stays three positional arguments (wildscan and
    run_export pass exactly those); behaviour switches travel as RS_EXPORT_*
    variables, which run_batch_script copies into the child environment. A
    switch given on the command line always WINS over an inherited value -
    --save clears an inherited RS_EXPORT_NO_SAVE, --only all clears both PLY
    switches - so an unattended run can state every one explicitly
    (AGENT_OPERATIONS sec. 5: no inheritance of science arguments). Paths
    given here are made absolute (backslashes), the form the .bat accepts.
    """
    if args.suffix is not None:
        os.environ['RS_EXPORT_SUFFIX'] = args.suffix
    if args.textures is not None:
        os.environ['RS_EXPORT_TEXTURES'] = args.textures
    no_save = getattr(args, 'no_save', None)
    if no_save is True:
        os.environ['RS_EXPORT_NO_SAVE'] = '1'
    elif no_save is False:
        os.environ.pop('RS_EXPORT_NO_SAVE', None)
    if args.only is not None:
        os.environ.pop('RS_EXPORT_SKIP_PLY', None)
        os.environ.pop('RS_EXPORT_ONLY_PLY', None)
        if args.only == 'meshes':
            os.environ['RS_EXPORT_SKIP_PLY'] = '1'
        elif args.only == 'ply':
            os.environ['RS_EXPORT_ONLY_PLY'] = '1'
    for attr, key in zip(('target_log', 'target_params', 'registration_dir'),
                         PATH_SWITCHES):
        value = getattr(args, attr, None)
        if value is not None:
            os.environ[key] = os.path.abspath(value)
    # Same checks the .bat makes before boot - here they cost nothing.
    export_suffix()
    expected_kinds()
    textures = os.environ.get('RS_EXPORT_TEXTURES', 'png').lower()
    if textures not in TEXTURE_FORMATS:
        raise ValueError(f'RS_EXPORT_TEXTURES={textures!r}: must be one of '
                         f'{TEXTURE_FORMATS}')
    check_path_switches()


def check_path_switches() -> None:
    """The .bat's before-boot refusals for the target log and the poses dir.

    RS_EXPORT_TARGET_LOG + RS_EXPORT_TARGET_PARAMS (both or neither, both
    existing files) make the .bat import the log and -update before any
    export; RS_EXPORT_REGISTRATION_DIR makes it write <dir>/<component>.csv
    of camera poses first. All three are expanded into cmd command lines, so
    they carry the .bat's path whitelist.
    """
    for key in PATH_SWITCHES:
        value = os.environ.get(key)
        if value and not PATH_RE.match(value):
            raise ValueError(
                f"{key}={value!r}: letters, digits, space and _ - . \\ : ' + "
                '# @ $ { } [ ] only - it is expanded into a command line, and '
                'ExportDeliverables.bat refuses anything else before boot.')
    log = os.environ.get('RS_EXPORT_TARGET_LOG')
    params = os.environ.get('RS_EXPORT_TARGET_PARAMS')
    if bool(log) != bool(params):
        raise ValueError('RS_EXPORT_TARGET_LOG and RS_EXPORT_TARGET_PARAMS go '
                         'together: the target log is imported with those '
                         'params or not at all.')
    for key, value in (('RS_EXPORT_TARGET_LOG', log),
                       ('RS_EXPORT_TARGET_PARAMS', params)):
        if value and not os.path.isfile(value):
            raise ValueError(f'{key}: no such file: {value!r}')


def registration_clashes(names: list[str]) -> list[str]:
    """Listed components whose poses CSV already exists (the .bat refuses:
    -exportRegistration has returned 0 without writing, so an old file would
    pass for a new one, and a record is never overwritten)."""
    reg = os.environ.get('RS_EXPORT_REGISTRATION_DIR')
    if not reg:
        return []
    return [n for n in names if os.path.exists(os.path.join(reg, n + '.csv'))]


def registration_problems(names: list[str]) -> list[str]:
    """After a run: why a listed component's poses CSV is absent or is not the
    camera-poses format ([] = every one is there and right, or not asked)."""
    reg = os.environ.get('RS_EXPORT_REGISTRATION_DIR')
    if not reg:
        return []
    problems = []
    for name in names:
        path = os.path.join(reg, name + '.csv')
        try:
            with open(path, encoding='utf-8-sig', errors='replace') as fh:
                first, second = fh.readline(), fh.readline()
        except OSError:
            problems.append(f'{name}: no {path}')
            continue
        if not re.match(r'#cameras \d+', first) or not second.startswith(POSES_HEADER):
            problems.append(f'{name}: {path} is not in the camera-poses format')
    return problems


def run_export(project: str, exports_dir: str, names_file: str,
               log_dir: str = None, logger: logging.Logger = None,
               settings: SettingsStore = None):
    """Run ExportDeliverables.bat through the unified execution layer.

    Same argument contract as the .bat itself (%1 .rsproj project path,
    %2 output directory, %3 component-name list file - one name per
    line). ``log_dir`` defaults to ``<exports parent>/logs``, which for a
    workspace's ``exports/`` folder is the workspace ``logs/`` directory
    every other stage driver writes to. Returns the ``WorkflowResult``.
    """
    logger = logger or logging.getLogger('export_deliverables')
    settings = settings or SettingsStore()
    # Machine constants from the single source of truth (RS_INSTANCE /
    # RS_HEADLESS / RS_CACHE_DIR). Environment wins over stored values, so
    # a portal/driver that already exported RS_* is passed through
    # unchanged and this update is a no-op for it.
    os.environ.update(realityscan_env(settings))
    if log_dir is None:
        log_dir = os.path.join(
            os.path.dirname(os.path.abspath(exports_dir)) or '.', 'logs')
    cli = RealityScanCLI(logger, settings)
    return cli.run_batch_script(
        'ExportDeliverables.bat',
        [str(project), str(exports_dir), str(names_file)], str(log_dir))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--project', required=True,
                        help='.rsproj assembly project path')
    parser.add_argument('--exports', required=True,
                        help='output directory (per-component subfolders '
                             'are created by the workflow)')
    parser.add_argument('--names', required=True,
                        help='component-name list file, one name per line')
    parser.add_argument('--log_dir', default=None,
                        help='driver log directory '
                             '(default: <exports parent>/logs)')
    parser.add_argument('--flight-log', default=None,
                        help='zone-tagged flight log whose UTM zone becomes '
                             'the export CRS; overrides --crs')
    parser.add_argument('--crs', default=None,
                        help='output coordinate system as authority:id '
                             '(e.g. epsg:32653). Without one the export '
                             'uses an inherited RS_PROJECT_CRS or, failing '
                             'that, whatever CRS the app last held')
    parser.add_argument('--suffix', default=None,
                        help='appended to every OUTPUT folder and file stem '
                             '(RS_EXPORT_SUFFIX), e.g. _L. Components and '
                             'models are still selected by their existing '
                             'names. Letters, digits, _ and - only')
    parser.add_argument('--textures', default=None, choices=TEXTURE_FORMATS,
                        help='texture format of the OBJ/FBX presets '
                             '(RS_EXPORT_TEXTURES; default png)')
    save = parser.add_mutually_exclusive_group()
    save.add_argument('--no-save', dest='no_save', action='store_const',
                      const=True, default=None,
                      help='never -save the project (RS_EXPORT_NO_SAVE): '
                           'no residual sweep, no save - for exporting '
                           'from a delivered or snapshotted project')
    save.add_argument('--save', dest='no_save', action='store_const',
                      const=False,
                      help='clear an inherited RS_EXPORT_NO_SAVE: sweep '
                           'residuals and -save before exporting, as by '
                           'default')
    parser.add_argument('--only', default=None,
                        choices=('all', 'meshes', 'ply'),
                        help='all (default), meshes = OBJ+FBX '
                             '(RS_EXPORT_SKIP_PLY), ply = dense PLY only '
                             '(RS_EXPORT_ONLY_PLY)')
    parser.add_argument('--target-log', default=None,
                        help='flight log whose positions ARE the wanted '
                             'camera positions (RS_EXPORT_TARGET_LOG): '
                             'imported and -update run after the CRS pin, '
                             'before any export, never saved. Needs '
                             '--target-params')
    parser.add_argument('--target-params', default=None,
                        help='FlightLogParams .xml to import --target-log '
                             'with (RS_EXPORT_TARGET_PARAMS)')
    parser.add_argument('--registration-dir', default=None,
                        help='write <dir>/<component>.csv of camera poses '
                             '(format {...0A4A}) per listed component before '
                             'the model exports (RS_EXPORT_REGISTRATION_DIR); '
                             'an existing CSV there is refused')
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    logger = logging.getLogger('export_deliverables')

    try:
        apply_switches(args)
    except ValueError as exc:
        logger.error('%s', exc)
        return 1

    # Fail fast, before an instance boots: the .bat checks these too, but
    # by then a RealityScan session is already the cost of the message.
    if not os.path.isfile(args.project):
        logger.error('assembly project not found: %r - has the '
                     'merge/model stage produced one?', args.project)
        return 1
    if not os.path.isfile(args.names):
        logger.error('component name list not found: %r', args.names)
        return 1
    # An EMPTY (or whitespace-only) list makes the .bat's `for /f` loop run
    # ZERO iterations, -quit, and exit 0: a no-op that reports success and
    # produces no deliverables at all (audit 2026-08-07).
    try:
        names = read_component_names(args.names)
    except OSError as exc:
        logger.error('cannot read component name list %r: %s', args.names, exc)
        return 1
    if not names:
        logger.error('component name list %r names NOTHING - the export '
                     'workflow would boot RealityScan, export zero '
                     'components and exit 0. Populate it from the merge '
                     "report's final_components first.", args.names)
        return 1
    unsafe = unsafe_component_names(names)
    if unsafe:
        logger.error('component name(s) %s contain cmd metacharacters; the '
                     '.bat re-parses every list line through `call`, so they '
                     'would be corrupted or executed. Rename them.', unsafe)
        return 1
    clashes = registration_clashes(names)
    if clashes:
        logger.error('RS_EXPORT_REGISTRATION_DIR %r already holds the poses '
                     'CSV of %s; the workflow refuses to overwrite a record '
                     '(and an old CSV would pass for a new one). Use a fresh '
                     'directory.', os.environ['RS_EXPORT_REGISTRATION_DIR'],
                     ', '.join(clashes))
        return 1
    suffix = export_suffix()
    logger.info('exporting %d component(s): %s', len(names), ', '.join(names))
    logger.info('output stems carry suffix %r; textures %s; project save %s; '
                'formats %s', suffix,
                os.environ.get('RS_EXPORT_TEXTURES', 'png'),
                'DISABLED' if os.environ.get('RS_EXPORT_NO_SAVE') else 'after sweep',
                '+'.join(expected_kinds()))
    if os.environ.get('RS_EXPORT_TARGET_LOG'):
        logger.info('exact-target georegistration: %s imported with %s, then '
                    '-update, in memory only',
                    os.environ['RS_EXPORT_TARGET_LOG'],
                    os.environ['RS_EXPORT_TARGET_PARAMS'])
    if os.environ.get('RS_EXPORT_REGISTRATION_DIR'):
        logger.info('camera poses per component to %s',
                    os.environ['RS_EXPORT_REGISTRATION_DIR'])

    # Output CRS. The exports are raw metric coordinates; the coordinate
    # SYSTEM they are stamped with comes from the application, and nothing
    # here ever set it - H2077 (a 53N cruise) exported as
    # "epsg:32757 - UTM zone 57S", the stale FlightLogParams placeholder
    # zone (2026-08-14). write_flight_log_params only governs the CRS of
    # the flight log being IMPORTED, never the export.
    # Merge 2026-09-03: the remove-xmp-sidecars branch carried this as
    # RS_OUTPUT_CRS; it is folded into main's repo-wide RS_PROJECT_CRS, the
    # variable realityscan_interface.py sets at align time from the flight
    # log's zone and AlignZone.bat / ExportDeliverables.bat consume. An
    # inherited RS_PROJECT_CRS is honoured when neither flag is given;
    # --flight-log overrides both.
    crs = args.crs or os.environ.get('RS_PROJECT_CRS')
    if args.flight_log:
        derived = crs_for_flight_log(args.flight_log)
        if derived:
            crs = derived.lower()
        else:
            logger.error('--flight-log %r carries no UTM zone tag, so no '
                         'export CRS could be derived from it',
                         args.flight_log)
            return 1
    if crs:
        os.environ['RS_PROJECT_CRS'] = crs
        logger.info('export coordinate system (RS_PROJECT_CRS): %s', crs)
    else:
        logger.warning(
            'No export CRS given (--crs / --flight-log) and RS_PROJECT_CRS '
            'is not set. The models will be stamped with whatever coordinate '
            'system the application last held, which is NOT necessarily '
            'this cruise - pass one.')

    # Prompt-with-default on a TTY, silent stored/fallback when unattended
    # (SettingsStore.ask); values already in the environment are never
    # prompted for or demoted (same pattern as run_models.py).
    settings = SettingsStore()
    if not os.environ.get('RS_INSTANCE'):
        settings.ask('realityscan', 'instance_name', None, 'RS1')
    if not os.environ.get('RS_CACHE_DIR'):
        settings.ask('realityscan', 'cache_dir', None, '')

    result = run_export(args.project, args.exports, args.names,
                        log_dir=args.log_dir, logger=logger,
                        settings=settings)
    if result.success:
        missing = missing_exports(args.exports, names)
        if missing:
            logger.error(
                'export workflow returned success but %d of %d expected '
                'deliverable folder(s) hold no file: %s. RealityScan reports '
                'success for do-nothing exports (a selection-driven export '
                'under -silent can export NOTHING), so the exit code alone '
                'proves nothing. Log: %s',
                len(missing), len(names) * len(expected_kinds()),
                ', '.join(missing[:12]) + (' ...' if len(missing) > 12 else ''),
                result.log_path)
            return 1
        # A preset key RealityScan does not honour is silent: the export
        # "succeeds" and writes PNG. The files are the evidence.
        if os.environ.get('RS_EXPORT_TEXTURES', 'png').lower() == 'jpg' \
                and 'obj' in expected_kinds():
            from modules.export_remaining import texture_problems
            problems = [p for name in names
                        for p in texture_problems(args.exports, name, suffix, 'jpg')]
            if problems:
                logger.error('export returned success but %d texture '
                             'reference(s) are not JPG: %s', len(problems),
                             '; '.join(problems[:8]))
                return 1
        # The .bat gates each CSV on its first two lines already; the census
        # repeats it from disk, like every other deliverable here.
        problems = registration_problems(names)
        if problems:
            logger.error('export returned success but %d poses CSV(s) are '
                         'missing or in the wrong format: %s', len(problems),
                         '; '.join(problems[:8]))
            return 1
        logger.info('export deliverables succeeded in %.1f min. '
                    '%d component(s) exported to %s. Log: %s',
                    result.duration_seconds / 60, len(names), args.exports,
                    result.log_path)
        return 0
    logger.error('export deliverables FAILED (exit %s, %s). Log: %s',
                 result.return_code, result.errors or '<no error detail>',
                 result.log_path)
    return 1


if __name__ == '__main__':
    sys.exit(main())
