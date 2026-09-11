"""Deterministic single-dive navigation entry point with read-only originals.

The legacy expedition commands remain available. This entry point separates
source copies from derived data and never writes into a source expedition.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import uuid

if __package__:
    from .processors import dive_summaries, process_dat, usbl_sdyn, sensors_sealog
    from .processors import kalman_concat, kalman_filter
    from .processors.report import stage_status
else:
    from processors import dive_summaries, process_dat, usbl_sdyn, sensors_sealog
    from processors import kalman_concat, kalman_filter
    from processors.report import stage_status

GIB = 1024 ** 3
COVERAGE_VERSION = 1


def _check_cancelled(cancelled):
    if cancelled is not None and cancelled():
        raise InterruptedError('Navigation source planning cancelled')


def _coverage_identity(path: Path) -> dict:
    stat = path.stat()
    return {'version': COVERAGE_VERSION, 'path': str(path.resolve()),
            'bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns,
            'ctime_ns': stat.st_ctime_ns, 'device': stat.st_dev, 'inode': stat.st_ino}


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def log_window_selection(path: Path, launch: datetime, recovery: datetime, *,
                         coverage_cache=None, cancelled=None, progress=None) -> str:
    """Select by record time, never filename date; unknown coverage is included.

    Stop on the first in-window record. Otherwise scan the complete log so renamed,
    multi-day and out-of-order records cannot be omitted by filename heuristics.
    The SDYN prefix margin is the parser's acquisition/receipt disagreement bound.
    Bare legacy GGA remains included for explicit filename fallback/diagnosis.
    """
    _check_cancelled(cancelled)
    before = _coverage_identity(path)
    key = before['path']
    window = [launch.isoformat(), recovery.isoformat(), usbl_sdyn.MAX_PREFIX_SKEW_SECONDS]
    cached = coverage_cache.get(key) if coverage_cache is not None else None
    margin = timedelta(seconds=usbl_sdyn.MAX_PREFIX_SKEW_SECONDS if path.suffix.lower() == '.sdyn' else 0)
    if isinstance(cached, dict) and cached.get('identity') == before:
        decision = None
        if cached.get('window') == window:
            decision = cached.get('decision')
        elif cached.get('complete'):
            try:
                earliest = datetime.fromisoformat(cached['earliest']) if cached['earliest'] else None
                latest = datetime.fromisoformat(cached['latest']) if cached['latest'] else None
                if earliest is None or latest < launch - margin or earliest > recovery + margin:
                    decision = 'unknown_coverage_included' if cached['unknown'] or earliest is None else 'outside_record_window'
            except (KeyError, TypeError, ValueError):
                pass  # Incompatible cache entries are advisory misses.
        if decision in ('record_time_overlaps_window', 'unknown_coverage_included', 'outside_record_window'):
            if progress:
                progress(0, 0, f'Cached record-time coverage: {path}')
            _check_cancelled(cancelled)
            if before != _coverage_identity(path):
                raise ValueError(f'Source changed during time-window inventory: {path}')
            return decision
    found_time, unknown = False, False
    result = None
    earliest = latest = None
    lines = 0
    if progress:
        progress(0, 0, f'Scanning record-time coverage: {path}')
    _check_cancelled(cancelled)
    with path.open(encoding='utf-8', errors='replace') as stream:
        for lines, line in enumerate(stream, 1):
            if lines % 4096 == 0:
                if progress:
                    progress(0, 0, f'Scanning record-time coverage: {path}; {lines} lines')
                _check_cancelled(cancelled)
            if not line.strip():
                continue
            if path.suffix.lower() == '.sdyn':
                match = re.match(r'^SDYN\s+(\S+)\s+SONARDYNE\s+\$GPGGA,', line)
                if not match:
                    unknown = True
                    continue
                stamp = match.group(1)
            else:
                match = re.match(r'^\S+\s+(\d{4}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s', line)
                if not match:
                    continue  # Untimestamped continuation lines are not new fixes.
                stamp = match.group(1).replace('/', '-') + 'T' + match.group(2) + '+00:00'
            try:
                time = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
                if time.tzinfo is None or time.utcoffset() != timedelta(0):
                    raise ValueError('UTC required')
            except ValueError:
                unknown = True
                continue
            found_time = True
            earliest = time if earliest is None else min(earliest, time)
            latest = time if latest is None else max(latest, time)
            if launch - margin <= time <= recovery + margin:
                result = 'record_time_overlaps_window'
                break
    _check_cancelled(cancelled)
    if before != _coverage_identity(path):
        raise ValueError(f'Source changed during time-window inventory: {path}')
    decision = result or ('unknown_coverage_included' if unknown or not found_time else 'outside_record_window')
    if coverage_cache is not None:
        coverage_cache[key] = {'identity': before, 'window': window, 'decision': decision,
                               'complete': result is None, 'unknown': unknown, 'lines': lines,
                               'earliest': earliest.isoformat() if earliest else None,
                               'latest': latest.isoformat() if latest else None}
    return decision


def manifested_log_files(plan: dict, *, verify_hashes: bool = False) -> dict:
    """Validate destinations and return exactly the manifested DAT/SDYN files."""
    project = Path(plan['project']).resolve()
    source = Path(plan['source']).resolve()
    root = Path(plan['raw_root']).resolve()
    if not root.is_relative_to(project) or source.is_relative_to(project) or project.is_relative_to(source):
        raise ValueError('Manifest source/project/raw-root containment mismatch')
    selected = {'.dat': [], '.sdyn': []}
    seen = set()
    for entry in plan['files']:
        path = Path(entry['copy']).resolve()
        if not path.is_relative_to(root) or path in seen:
            raise ValueError(f'Duplicate or escaping manifest destination: {path}')
        seen.add(path)
        suffix = path.suffix.lower()
        if suffix not in selected:
            continue
        expected = root / ('raw/nav/navest' if suffix == '.dat' else 'raw/datalog')
        if path.parent != expected:
            # Dive reports may legitimately contain auxiliary .dat files (e.g.
            # SVP profiles). They remain copied but are not NavEst sensor logs.
            relative = path.relative_to(root)
            if relative.parts[:2] in (('raw', 'nav'), ('raw', 'datalog')):
                raise ValueError(f'Log outside its manifested sensor directory: {path}')
            continue
        if verify_hashes and (not path.is_file() or entry.get('sha256') != digest(path)):
            raise ValueError(f'Manifested input missing or hash differs: {path}')
        selected[suffix].append(path)
    return {suffix: sorted(paths) for suffix, paths in selected.items()}


def source_window(source: Path, project: Path, expedition: str, dive: str) -> dict:
    """Validate delivery layout and dive report, without enumerating sensor logs.

    Returns JSON-compatible UTC window and common roots. No writes, content
    hashes, sensor coverage scans or navigation-completeness claims are made.
    Statistics ambiguity/chronology retain the shared dive-summary validation.
    """
    if not re.fullmatch(r"NA\d+", expedition) or not re.fullmatch(r"H\d+", dive):
        raise ValueError("Expected expedition NA<number> and dive H<number>")
    source, project = Path(source).resolve(), Path(project).resolve()
    if project.is_relative_to(source) or source.is_relative_to(project):
        raise ValueError("Source and project trees must be separate")
    roots = [p for p in (source, source / "cruise_data") if (p / "raw").is_dir()]
    if len(roots) != 1:
        raise ValueError(f"Expected one cruise-data root; found {roots}")
    root = roots[0]
    reports = [p for p in (root / "processed" / "dive_reports",
                           root / "proc" / "processed" / "dive_reports")
               if (p / dive).is_dir()]
    if len(reports) != 1:
        raise ValueError(f"Expected one {dive} dive-report folder; found {reports}")
    frame = dive_summaries.process_dive_folder(reports[0] / dive, dive)
    if frame is None or len(frame) != 1:
        raise ValueError("Exactly one valid dive-statistics row is required")
    row = frame.iloc[0]
    if str(row["expedition"]).strip() != expedition or str(row["dive"]).strip() != dive:
        raise ValueError("Dive statistics disagree with selected expedition/dive")
    launch = datetime.fromisoformat(str(row["Launch Time"]).replace("Z", "+00:00"))
    recovery = datetime.fromisoformat(str(row["Recovery Time"]).replace("Z", "+00:00"))
    if any(t.tzinfo is None or t.utcoffset() != timedelta(0) for t in (launch, recovery)) or launch >= recovery:
        raise ValueError('Dive launch/recovery must be ordered explicit UTC timestamps')
    return {'schema_version': 1, 'expedition': expedition, 'dive': dive,
            'source': str(source), 'project': str(project),
            'delivery_root': str(root), 'reports_root': str(reports[0]),
            'dive_report_root': str(reports[0] / dive),
            'navest_root': str(root / 'raw/nav/navest'),
            'sdyn_root': str(root / 'raw/datalog'),
            'sealog_root': str(root / 'raw/sealog/sealog-herc' / dive),
            'raw_root': str(project / 'raw/navigation' / expedition),
            'launch_utc': launch.isoformat(), 'recovery_utc': recovery.isoformat()}


def source_plan(source: Path, project: Path, expedition: str, dive: str, *,
                coverage_cache=None, cancelled=None, progress=None) -> dict:
    """Build full manifest after cheap source_window validation.

    Optional caller-owned coverage_cache is a metadata-identity optimization,
    not a content fingerprint. progress(current, total, message) uses file counts;
    cancelled() raising/returning true aborts without publishing a partial plan.
    """
    _check_cancelled(cancelled)
    window = source_window(source, project, expedition, dive)
    root = Path(window['delivery_root'])
    launch = datetime.fromisoformat(window['launch_utc'])
    recovery = datetime.fromisoformat(window['recovery_utc'])
    selected = []
    log_selection = []
    logs = []
    for folder, suffix in ((Path(window['navest_root']), ".dat"),
                           (Path(window['sdyn_root']), ".sdyn")):
        _check_cancelled(cancelled)
        if not folder.is_dir():
            raise FileNotFoundError(folder)
        for path in sorted(folder.iterdir()):
            _check_cancelled(cancelled)
            if not path.is_file() or path.suffix.lower() != suffix:
                continue
            logs.append(path)
    for index, path in enumerate(logs):
        def scan_progress(_current, _total, message):
            if progress:
                progress(index, len(logs), message)
        decision = log_window_selection(path, launch, recovery, coverage_cache=coverage_cache,
                                         cancelled=cancelled, progress=scan_progress if progress else None)
        log_selection.append({'source': str(path), 'decision': decision})
        if decision != 'outside_record_window':
            selected.append((path, path.relative_to(root)))
        if progress:
            progress(index + 1, len(logs), f'{decision}: {path}')
    for folder, target in ((Path(window['dive_report_root']), Path("processed/dive_reports") / dive),
                           (Path(window['sealog_root']),
                            Path("raw/sealog/sealog-herc") / dive)):
        if not folder.is_dir():
            raise FileNotFoundError(folder)
        for path in sorted(folder.rglob("*")):
            _check_cancelled(cancelled)
            if path.is_file():
                selected.append((path, target / path.relative_to(folder)))
    raw_root = Path(window['raw_root'])
    files = [{"source": str(p), "copy": str(raw_root / rel),
              "bytes": p.stat().st_size, "mtime_ns": p.stat().st_mtime_ns}
             for p, rel in selected]
    _check_cancelled(cancelled)
    return {**window,
            "selection": "Dive report and sealog; DAT/SDYN record-time overlap, unknown coverage retained for diagnosis",
            "log_selection": log_selection,
            "files": files, "copy_bytes": sum(f["bytes"] for f in files)}


def copy_inputs(plan: dict, reserve_bytes: int) -> None:
    """Copy immutable inputs with hashes and enforce reserve before every chunk."""
    manifested_log_files(plan)
    if not isinstance(reserve_bytes, (int, float)) or not math.isfinite(reserve_bytes) or reserve_bytes < 0:
        raise ValueError('Reserve must be finite and nonnegative')
    project = Path(plan["project"])
    project.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(project).free < plan["copy_bytes"] + reserve_bytes:
        raise OSError("Insufficient space for navigation copies plus the free-space reserve")
    for item in plan["files"]:
        source, target = Path(item["source"]), Path(item["copy"])
        before = source.stat()
        if (before.st_size, before.st_mtime_ns) != (item["bytes"], item["mtime_ns"]):
            raise ValueError(f"Source changed after inventory: {source}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if digest(source) != digest(target):
                raise FileExistsError(f"Existing raw copy differs: {target}")
        else:
            temp = target.with_name(target.name + f".{uuid.uuid4().hex}.partial")
            try:
                with source.open("rb") as src, temp.open("xb") as dst:
                    while chunk := src.read(8 * 1024 * 1024):
                        if shutil.disk_usage(project).free < reserve_bytes + len(chunk):
                            raise OSError("Free-space reserve reached while copying navigation")
                        dst.write(chunk)
                if digest(source) != digest(temp):
                    raise IOError(f"Copy verification failed: {source}")
                temp.rename(target)
                shutil.copystat(source, target)
            finally:
                temp.unlink(missing_ok=True)
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError(f"Source changed during copy: {source}")
        item["sha256"] = digest(target)


def run_navigation(plan: dict, reserve_bytes: int = 50 * GIB) -> Path:
    """Create a fresh attributable attempt; an exit code alone is not success."""
    copy_inputs(plan, reserve_bytes)
    log_files = manifested_log_files(plan, verify_hashes=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    attempt = Path(plan["project"]) / "proc/navigation" / run_id
    output = attempt / plan["expedition"] / "RUMI_processed"
    output.mkdir(parents=True)
    (attempt / "source_manifest.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    root, dive = Path(plan["raw_root"]), plan["dive"]
    reports = root / "processed/dive_reports"
    for module, kwargs in (
        (dive_summaries, {"reports_dir": reports, "dive": dive}),
        (process_dat, {"files": log_files['.dat']}),
        (usbl_sdyn, {"files": log_files['.sdyn']}),
        (sensors_sealog, {"reports_dir": reports}),
    ):
        module.process_data(root, output_dir=output, **kwargs)
        name = module.__name__.rsplit(".", 1)[-1]
        if stage_status(output, name) != "ok":
            raise RuntimeError(f"Navigation extraction failed: {name}")
    dive_output = output / dive
    for module in (kalman_concat, kalman_filter):
        module.process_data(dive_output, dive_output)
        name = module.__name__.rsplit(".", 1)[-1]
        if stage_status(dive_output, name) != "ok":
            raise RuntimeError(f"Navigation processing failed: {name}")
    final = dive_output / f"{plan['expedition']}_{dive}_final_datatable.csv"
    if not final.is_file() or final.stat().st_size == 0:
        raise RuntimeError("Missing final vehicle navigation table")
    # This is vehicle navigation, deliberately excluding kalman_offset's
    # terrain/visualisation displacement. Approval remains a project concern.
    (attempt / "navigation_result.json").write_text(json.dumps({
        "schema_version": 1, "run_id": run_id, "navigation": str(final),
        "sha256": digest(final), "state": "candidate_pending_quality_review",
        "vertical_reference": "negative pressure depth; sea-surface datum not independently verified",
        "terrain_offset_applied": False}, indent=2), encoding="utf-8")
    return final


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--expedition", required=True)
    parser.add_argument("--dive", required=True)
    parser.add_argument("--execute", action="store_true", help="Copy and process; default only prints the plan")
    parser.add_argument("--reserve-gib", type=float, default=50)
    args = parser.parse_args(argv)
    if not math.isfinite(args.reserve_gib) or args.reserve_gib < 0:
        parser.error("reserve must be nonnegative")
    plan = source_plan(args.source, args.project, args.expedition.upper(), args.dive.upper())
    print(json.dumps({k: v for k, v in plan.items() if k != "files"} |
                     {"file_count": len(plan["files"])}, indent=2))
    if args.execute:
        print(run_navigation(plan, int(args.reserve_gib * GIB)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
