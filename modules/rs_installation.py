"""Read-only RealityScan 2.2 audit and explicitly selected XML repairs.

No application execution, settings inheritance, automatic install discovery
fallback, or implicit repair. See docs/REALITYSCAN_INSTALLATION.md.
"""
from __future__ import annotations

import argparse
import ctypes
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import uuid
import xml.etree.ElementTree as ET
from xml.parsers import expat

from . import flightlog_format as formats

DEFAULT_INSTALL_DIR = formats.INSTALL_DIRS[0]
_METADATA = Path(__file__).parent / 'realityscan_interface/RS_CLI/Metadata'
DEFAULT_PARAMS = (
    (_METADATA / 'FlightLogParams.xml', 'flightlogs.xml', formats.FLIGHTLOG_FORMAT_KEY),
    (_METADATA / 'FlightLogParamsLocal.xml', 'flightlogs.xml', formats.FLIGHTLOG_FORMAT_KEY),
    (_METADATA / 'RegistrationExportParams.xml', 'calibration.xml',
     formats.CALIBRATION_EXPORT_FORMAT_KEY),
)
SCHEMA_VERSION = 1
# The repository calibration file is an extension catalog, not a vendor-file
# replacement. Its wrapper differs from the shipped application's wrapper.
_MANAGED_ROOTS = {'flightlogs.xml': {'FlightLogs'},
                  'calibration.xml': {'Calibration', 'CalibrationExport'}}


class InstallationError(RuntimeError):
    """Inspection or repair cannot establish the required installation state."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _read_version(executable: Path) -> dict:
    """Read Windows version resources, without loading or launching the exe."""
    if os.name != 'nt':
        raise InstallationError('Windows version-resource inspection requires Windows')
    from ctypes import wintypes

    api = ctypes.WinDLL('version', use_last_error=True)
    api.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    api.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    api.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                      wintypes.DWORD, ctypes.c_void_p]
    api.GetFileVersionInfoW.restype = wintypes.BOOL
    api.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                  ctypes.POINTER(ctypes.c_void_p),
                                  ctypes.POINTER(wintypes.UINT)]
    api.VerQueryValueW.restype = wintypes.BOOL
    ignored = wintypes.DWORD()
    size = api.GetFileVersionInfoSizeW(str(executable), ctypes.byref(ignored))
    if not size:
        raise InstallationError('Executable has no readable Windows version resource')
    buffer = ctypes.create_string_buffer(size)
    if not api.GetFileVersionInfoW(str(executable), 0, size, buffer):
        raise InstallationError('Cannot read executable version resource')

    def query(key):
        pointer, length = ctypes.c_void_p(), wintypes.UINT()
        if not api.VerQueryValueW(buffer, key, ctypes.byref(pointer), ctypes.byref(length)):
            raise InstallationError(f'Missing executable version field: {key}')
        return pointer, length.value

    pointer, length = query('\\')
    if length < 13 * 4:
        raise InstallationError('Truncated fixed version resource')
    fixed = ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD * 13)).contents
    if fixed[0] != 0xFEEF04BD:
        raise InstallationError('Invalid fixed version resource signature')

    def version(ms, ls):
        return '.'.join(map(str, (ms >> 16, ms & 65535, ls >> 16, ls & 65535)))

    pointer, length = query('\\VarFileInfo\\Translation')
    if length < 4:
        raise InstallationError('Missing version-resource translation')
    words = ctypes.cast(pointer, ctypes.POINTER(wintypes.WORD * 2)).contents
    def string(key):
        pointer, length = query(f'\\StringFileInfo\\{words[0]:04x}{words[1]:04x}\\{key}')
        return ctypes.wstring_at(pointer, length).rstrip('\0')

    # Build 119430 exceeds the fixed resource's 16-bit component and is
    # truncated to 53894. Keep both representations; never relabel that build.
    return {'file_version': string('FileVersion'),
            'product_version': string('ProductVersion'),
            'product_name': string('ProductName'),
            'fixed_file_version': version(fixed[2], fixed[3]),
            'fixed_product_version': version(fixed[4], fixed[5])}


def validate_installation(install_dir: str | Path | None = None) -> dict:
    """Validate exactly the selected directory (default: Epic RS 2.2)."""
    root = Path(DEFAULT_INSTALL_DIR if install_dir is None else install_dir).absolute()
    exe = root / 'RealityScan.exe'
    report = {'install_dir': str(root), 'executable': str(exe), 'valid': False,
              'version': None, 'executable_sha256': None, 'diagnostics': []}
    try:
        if not exe.is_file():
            raise InstallationError(f'RealityScan.exe is missing from {root}')
        before = _file_sha(exe)
        report['version'] = _read_version(exe)
        report['executable_sha256'] = _file_sha(exe)
        if before != report['executable_sha256']:
            raise InstallationError('Executable changed while reading its version')
        info = report['version']
        if (info['product_name'].strip().casefold() != 'realityscan'
                or any(not re.fullmatch(r'2\.2\.\d+\.\d+(?:\.RS)?', info[key])
                       for key in ('file_version', 'product_version'))
                or any(not re.fullmatch(r'2\.2\.\d+\.\d+', info[key])
                       for key in ('fixed_file_version', 'fixed_product_version') if key in info)):
            raise InstallationError(f'Only RealityScan 2.2 is supported; found {info}')
        report['valid'] = True
    except (OSError, InstallationError) as exc:
        report['diagnostics'].append(str(exc))
        report['diagnostics'].append(
            'Choose the folder containing RealityScan 2.2 and supply --install-dir PATH; '
            'older versions and similarly named directories are not accepted.')
    return report


def _semantic(element: ET.Element):
    # Dialog labels do not define the import/export contract. Formatting around
    # elements is irrelevant; internal body/template whitespace remains exact.
    attrs = {k: v for k, v in element.attrib.items() if k not in ('desc', 'descID')}
    if 'id' in attrs:
        attrs['id'] = attrs['id'].strip().upper()
    text = element.text or ''
    if element.tag != 'body':
        text = text.strip()
    return [element.tag, sorted(attrs.items()), text,
            [_semantic(child) for child in element], (element.tail or '').strip()]


def _format_info(element: ET.Element) -> dict:
    parser = element.find('parser')
    fields = [] if parser is None else [
        {'field': child.tag, **child.attrib} for child in parser]
    return {'guid': element.get('id', '').strip().upper(),
            'description': element.get('desc'),
            'sha256': _sha(json.dumps(_semantic(element), ensure_ascii=True).encode()),
            'fields': fields}


def _xml(path: Path) -> tuple[bytes, ET.Element, dict]:
    data = path.read_bytes()
    data.decode('utf-8-sig')  # Never silently rewrite an unsupported encoding.
    if b'<!DOCTYPE' in data or b'<!ENTITY' in data:
        raise InstallationError(f'DTD/entity declarations are unsupported: {path}')
    root = formats._parse(str(path))  # Existing reader handles RealityScan's &tab;.
    entries = {}
    for element in root.findall('format'):
        info = _format_info(element)
        guid = info['guid']
        if not re.fullmatch(r'\{[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}\}', guid):
            raise InstallationError(f'Invalid format GUID in {path}: {guid!r}')
        if guid in entries:
            raise InstallationError(f'Duplicate format GUID in {path}: {guid}')
        entries[guid] = info
    if path.read_bytes() != data:
        raise InstallationError(f'XML changed during inspection: {path}')
    return data, root, entries


def _inventory(path: Path) -> dict:
    report = {'path': str(path), 'sha256': None, 'root': None,
              'version': {}, 'formats': {}, 'error': None}
    try:
        report['sha256'] = _file_sha(path)
        data, root, entries = _xml(path)
        report.update(sha256=_sha(data), root=root.tag, version=dict(root.attrib), formats=entries)
    except (OSError, ValueError, ET.ParseError, InstallationError) as exc:
        report['error'] = str(exc)
    return report


def inspect_installation(install_dir: str | Path | None = None, *,
                         params_path: str | Path | None = None,
                         baseline: dict | None = None) -> dict:
    """JSON-ready inventory, required field maps, and optional snapshot drift.

    Only required GUID semantics block readiness; other vendor differences are
    reported. XML bytes need not match the repository or a previous snapshot.
    """
    installation = validate_installation(install_dir)
    root = installation['install_dir']
    report = {'schema_version': SCHEMA_VERSION, 'installation': installation,
              'ready': installation['valid'], 'managed_files': {},
              'required_formats': [], 'diagnostics': list(installation['diagnostics']),
              'drift': []}
    for name, repo_path in formats.MANAGED_FILES:
        installed = formats.installed_path(name, root)
        app = _inventory(Path(installed) if installed else Path(root) / name)
        repo = _inventory(Path(repo_path))
        have, want = app['formats'], repo['formats']
        item = {'application': app, 'repository': repo,
                'missing_guids': sorted(want.keys() - have.keys()),
                'extra_guids': sorted(have.keys() - want.keys()),
                'changed_guids': sorted(g for g in have.keys() & want.keys()
                                        if have[g]['sha256'] != want[g]['sha256'])}
        report['managed_files'][name] = item
        for side, inv in (('application', app), ('repository', repo)):
            if inv['error']:
                report['ready'] = False
                report['diagnostics'].append(f'{name} {side}: {inv["error"]}')
        if any(inv['root'] not in _MANAGED_ROOTS.get(name, set()) for inv in (app, repo)):
            report['ready'] = False
            report['diagnostics'].append(f'{name}: unrecognized application/repository XML root')
    requirements = list(DEFAULT_PARAMS)
    if params_path is not None:
        requirements.append((Path(params_path), 'flightlogs.xml', formats.FLIGHTLOG_FORMAT_KEY))
    for params, name, key in requirements:
        entry = {'params_path': str(params), 'file': name, 'key': key,
                 'guid': None, 'valid': False, 'expected_fields': [], 'installed_fields': []}
        try:
            guid = formats.configured_guid(str(params), key)
            entry['guid'] = guid
            tree = formats._parse(str(params))
            if len([e for e in tree.findall('entry') if e.get('key') == key]) != 1:
                raise InstallationError(f'Expected exactly one {key} entry')
            item = report['managed_files'][name]
            want = item['repository']['formats'].get(guid)
            have = item['application']['formats'].get(guid)
            entry['expected_fields'] = want['fields'] if want else []
            entry['installed_fields'] = have['fields'] if have else []
            entry['valid'] = bool(want and have and want['sha256'] == have['sha256'])
            if not entry['valid']:
                entry['error'] = 'Required GUID missing or its import/export contract differs'
        except (OSError, ValueError, ET.ParseError, InstallationError) as exc:
            entry['error'] = str(exc)
        if not entry['valid']:
            report['ready'] = False
            report['diagnostics'].append(f'{params}: {entry["error"]}')
        report['required_formats'].append(entry)
    if baseline is not None:
        if baseline.get('schema_version') != SCHEMA_VERSION:
            raise InstallationError('Unsupported baseline schema')
        if baseline['installation']['install_dir'] != root:
            raise InstallationError('Baseline belongs to a different installation directory')
        for key in ('version', 'executable_sha256'):
            if baseline['installation'].get(key) != installation[key]:
                report['drift'].append({'scope': 'installation', 'field': key,
                                        'before': baseline['installation'].get(key),
                                        'after': installation[key]})
        for name, item in report['managed_files'].items():
            for side in ('application', 'repository'):
                old = baseline.get('managed_files', {}).get(name, {}).get(side, {})
                for key in ('sha256', 'version'):
                    if old.get(key) != item[side][key]:
                        report['drift'].append({'scope': f'{side}/{name}', 'field': key,
                                                'before': old.get(key), 'after': item[side][key]})
    return report


def _spans(data: bytes) -> tuple[dict, int]:
    """Locate direct format elements without serializing vendor XML.

    Equal-length substitution retains Expat's byte offsets (including BOM,
    non-ASCII text, comments and CDATA). The tolerant shared reader validates
    the original document before this scanner is called.
    """
    parser = expat.ParserCreate()
    depth, start, guid, close = 0, 0, '', -1
    spans = {}

    def begin(tag, attrs):
        nonlocal depth, start, guid
        if depth == 1 and tag == 'format':
            start = parser.CurrentByteIndex
            guid = attrs['id'].strip().upper()
        depth += 1

    def end(tag):
        nonlocal depth, close
        depth -= 1
        offset = parser.CurrentByteIndex
        if depth == 1 and tag == 'format':
            # Expat reports the next byte for self-closing elements.
            finish = (data.index(b'>', offset) + 1
                      if data[offset:offset + 8] == b'</format' else offset)
            spans[guid] = (start, finish)
        elif depth == 0:
            close = offset

    parser.StartElementHandler = begin
    parser.EndElementHandler = end
    parser.Parse(data.replace(b'&tab;', b'&#09;'), True)
    if data[close:close + 2] != b'</':
        raise InstallationError('Self-closing XML root cannot be repaired safely')
    return spans, close


def _repair_paths(install_dir, filename):
    sources = dict(formats.MANAGED_FILES)
    if filename not in sources or Path(filename).name != filename:
        raise InstallationError('Repair filename must be a managed XML basename')
    root = Path(install_dir).absolute()
    target = root / filename
    for path in (target, *target.parents):
        if path.is_symlink() or path.is_junction():
            raise InstallationError(f'Repair refuses redirected paths: {path}')
    if not target.is_file() or target.stat().st_nlink != 1:
        raise InstallationError('Repair requires an existing, non-hardlinked installed XML')
    source = Path(sources[filename]).absolute()
    if source.resolve() == target.resolve():
        raise InstallationError('Application XML and repository XML must be different files')
    return target, source


def propose_repair(install_dir: str | Path | None, filename: str,
                   guids: list[str]) -> dict:
    """Return a concrete JSON proposal; never write anything or select all IDs."""
    installation = validate_installation(install_dir)
    if not installation['valid']:
        raise InstallationError('; '.join(installation['diagnostics']))
    target, source = _repair_paths(installation['install_dir'], filename)
    selected = sorted({g.strip().upper() for g in guids})
    if not selected:
        raise InstallationError('Choose at least one explicit format GUID')
    old, app_root, have = _xml(target)
    repo, repo_root, want = _xml(source)
    if any(root.tag not in _MANAGED_ROOTS.get(filename, set()) for root in (app_root, repo_root)):
        raise InstallationError('Unrecognized application/repository XML root')
    app_spans, close = _spans(old)
    repo_spans, _ = _spans(repo)
    edits, additions, actions = [], [], []
    newline = b'\r\n' if b'\r\n' in old else b'\n'
    for guid in selected:
        if guid not in want:
            raise InstallationError(f'GUID is not defined in the repository: {guid}')
        if guid in have and have[guid]['sha256'] == want[guid]['sha256']:
            raise InstallationError(f'GUID already matches; no repair needed: {guid}')
        first, last = repo_spans[guid]
        block = repo[first:last]
        actions.append({'guid': guid, 'action': 'replace' if guid in have else 'add',
                        'before': have.get(guid), 'after': want[guid]})
        if guid in have:
            edits.append((*app_spans[guid], block))
        else:
            additions.append(block)
    if additions:
        edits.append((close, close, newline + newline.join(additions) + newline))
    result = old
    for first, last, block in sorted(edits, reverse=True):
        result = result[:first] + block + result[last:]
    # Text content is reviewable and round-trips BOM/newlines through JSON.
    proposal = {'schema_version': SCHEMA_VERSION,
                'install_dir': installation['install_dir'], 'filename': filename,
                'target': str(target), 'source': str(source), 'selected_guids': selected,
                'version': installation['version'],
                'executable_sha256': installation['executable_sha256'],
                'before_sha256': _sha(old), 'source_sha256': _sha(repo),
                'after_sha256': _sha(result), 'actions': actions,
                'content': result.decode('utf-8'),
                'diff': ''.join(difflib.unified_diff(
                    old.decode('utf-8').splitlines(keepends=True),
                    result.decode('utf-8').splitlines(keepends=True),
                    fromfile=str(target), tofile=str(target) + ' (proposed)'))}
    proposal['repair_id'] = _sha(json.dumps(proposal, sort_keys=True).encode())
    return proposal


def apply_repair(proposal: dict, *, selected_repair_id: str) -> dict:
    """Apply exactly a reviewed proposal, with fresh validation and backup.

    A sibling lock serializes cooperating callers. External writers (including
    an updater) must be quiescent; hashes cannot eliminate their final race.
    """
    if not selected_repair_id or selected_repair_id != proposal.get('repair_id'):
        raise InstallationError('Explicit selected_repair_id must match the proposal')
    current = propose_repair(proposal['install_dir'], proposal['filename'], proposal['selected_guids'])
    if proposal != current:
        raise InstallationError('Stale or altered proposal; inspect and propose again')
    target, source = _repair_paths(current['install_dir'], current['filename'])
    lock = target.with_name(target.name + '.rs-installation.lock')
    temporary = None
    # Exclusive creation: never remove a lock owned by another caller.
    with lock.open('xb') as lock_stream:
        try:
            lock_stream.write(selected_repair_id.encode('ascii'))
            lock_stream.flush()
            os.fsync(lock_stream.fileno())
            original = target.read_bytes()
            content = current['content'].encode('utf-8')
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=target.name + '.',
                                             suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            _, _, repaired = _xml(temporary)
            _, _, original_formats = _xml(target)
            for guid, info in original_formats.items():
                if guid not in current['selected_guids'] and repaired.get(guid) != info:
                    raise InstallationError(f'Repair changed unselected format {guid}')
            for action in current['actions']:
                if repaired.get(action['guid']) != action['after']:
                    raise InstallationError('Repaired format failed postcondition')
            _repair_paths(current['install_dir'], current['filename'])
            if (_sha(original) != current['before_sha256']
                    or _file_sha(target) != current['before_sha256']
                    or _file_sha(source) != current['source_sha256']
                    or _file_sha(target.parent / 'RealityScan.exe') != current['executable_sha256']):
                raise InstallationError('Installation or repository changed before replacement')
            backup = target.with_name(target.name + '.' + uuid.uuid4().hex + '.bak')
            with backup.open('xb') as stream:
                stream.write(original)
                stream.flush()
                os.fsync(stream.fileno())
            if _file_sha(target) != current['before_sha256']:
                raise InstallationError('Installed XML changed while backing up; backup retained')
            os.replace(temporary, target)
            temporary = None
            if _file_sha(target) != current['after_sha256']:
                raise InstallationError(f'Post-replace hash mismatch; recover from {backup}')
            return {'repair_id': selected_repair_id, 'target': str(target),
                    'backup': str(backup), 'sha256': current['after_sha256']}
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            lock_stream.close()  # Windows cannot unlink an open file.
            lock.unlink()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    inspect = sub.add_parser('inspect', help='read-only JSON audit')
    inspect.add_argument('--install-dir')
    inspect.add_argument('--params', help='additional required flight-log params XML')
    inspect.add_argument('--baseline', type=Path)
    propose = sub.add_parser('propose', help='create a proposal, never modify the installation')
    propose.add_argument('--install-dir')
    propose.add_argument('--file', required=True, choices=[n for n, _ in formats.MANAGED_FILES])
    propose.add_argument('--guid', action='append', required=True)
    propose.add_argument('--output', required=True, type=Path)
    apply = sub.add_parser('apply', help='apply only the explicitly selected repair')
    apply.add_argument('proposal', type=Path)
    apply.add_argument('--repair-id', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'inspect':
            baseline = json.loads(args.baseline.read_text(encoding='utf-8-sig')) if args.baseline else None
            result = inspect_installation(args.install_dir, params_path=args.params, baseline=baseline)
            code = 0 if result['ready'] else 2
        elif args.command == 'propose':
            result = propose_repair(args.install_dir, args.file, args.guid)
            with args.output.open('x', encoding='utf-8', newline='\n') as stream:
                json.dump(result, stream, indent=2)
                stream.write('\n')
            code = 0
        else:
            result = apply_repair(json.loads(args.proposal.read_text(encoding='utf-8-sig')),
                                  selected_repair_id=args.repair_id)
            code = 0
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return code
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError, InstallationError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=True))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
