"""Materialize approved subsets and an exactly matching, zone-tagged flight log."""
from __future__ import annotations

import csv
from pathlib import Path
from uuid import uuid4

from .flight_logs import utm_zone_from_flight_log_name, epsg_for_utm_zone
from .project_reviews import ReviewStore, write_json
from .source_inventory import approval_token, file_hash, stage_inventory


def filter_flight_log(source, destination, items, *, expected_epsg):
    """Preserve original rows/precision; require one finite pose per kept image."""
    import math
    source, destination = Path(source), Path(destination)
    zone = utm_zone_from_flight_log_name(str(source))
    if zone is None or epsg_for_utm_zone(*zone) != expected_epsg:
        raise ValueError("Flight-log filename CRS disagrees with navigation")
    expected = {}
    for item in items:
        if item.kind == "image" and item.included and not item.duplicate_of:
            name = Path(item.path).name.casefold()
            if name in expected:
                raise ValueError("Kept camera images have ambiguous duplicate basenames")
            expected[name] = Path(item.path).name
    before = file_hash(source)
    with source.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, delimiter=";")
        header = next(reader)
        if len(header) != 14 or header[0].casefold() != "filename":
            raise ValueError("Expected the 14-column RealityScan camera flight log")
        rows = {}
        for row in reader:
            if not row:
                continue
            name = Path(row[0].replace("\\", "/")).name.casefold()
            if name not in expected:
                continue
            if name in rows:
                raise ValueError("Repeated flight-log pose for " + name)
            if len(row) != 14 or not all(math.isfinite(float(v)) for v in row[1:]):
                raise ValueError("Incomplete/nonfinite retained camera pose for " + name)
            rows[name] = [expected[name], *row[1:]]
    if file_hash(source) != before:
        raise ValueError("Flight log changed during selection")
    missing = set(expected) - set(rows)
    if missing:
        raise ValueError(f"{len(missing)} retained images have no flight-log pose")
    if not rows:
        raise ValueError("Empty retained image selection")
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / source.name
    temporary = destination / (source.name + "." + uuid4().hex + ".partial")
    try:
        with temporary.open("x", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, delimiter=";", lineterminator="\n")
            writer.writerow(header)
            writer.writerows(rows[name] for name in sorted(rows))
        if target.exists():
            if file_hash(target) != file_hash(temporary):
                raise ValueError("Existing selected flight log differs; create a new attempt")
        else:
            temporary.rename(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def materialize_selection(project, flight_log, *, expected_epsg, reserve_bytes, cancelled=lambda: False, progress=None):
    """Every caller passes both approvals before any downstream data is created."""
    store = ReviewStore(project)
    items = store.selection()
    token = approval_token(items)
    staged = stage_inventory(items, project.root, reserve_bytes=reserve_bytes,
        approved_token=token, cancelled=cancelled, progress=progress,
        images_relative_path=f"proc/selections/{token}/images")
    root = Path(staged["images_root"])
    log = filter_flight_log(flight_log, root.parent / "navigation", items, expected_epsg=expected_epsg)
    manifest = {"schema": 1, "project_id": project.project_id, "selection_hash": token,
        "quality_review_hash": store.require_approved("quality")["assessment_hash"],
        "spatial_review_hash": store.require_approved("spatial")["assessment_hash"],
        "images_root": str(root), "flight_log": str(log), "flight_log_sha256": file_hash(log),
        "epsg": expected_epsg,
        "masks": [{"path": path, "sha256": file_hash(Path(path))} for path in staged["outputs"]
                  if '.mask.' in Path(path).name.lower()],
        "images": [{"path": str(root / item.camera / Path(item.path).name), "sha256": item.sha256}
                   for item in items if item.kind == "image" and item.included and not item.duplicate_of]}
    path = root.parent / "selection.json"
    write_json(path, manifest)
    return manifest, path
