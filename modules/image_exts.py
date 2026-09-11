"""ONE inventory of image file extensions for the whole pipeline.

Five different literal sets used to be spelled out across
workspace_census, run_plan (ex wildscan/session), georeference, batch_directory,
camera_registry, realityscan_interface, merge_zones and grow_zone - so a
.tif or .heif dataset was "present" to some stages and invisible to
others: the census reported two images extracted while the georeferencer
silently produced priors for one (audit 2026-08-07).

Two names, both explicit about what they mean:

``ALL_IMAGE_EXTS``
    Everything the pipeline RECOGNISES as survey imagery. Use it for
    censuses, scans and "is there imagery here?" questions.

``PROCESSABLE_IMAGE_EXTS``
    What the timestamp/copy/sidecar stages actually handle today. It is a
    strict subset, and stages that use it MUST report what they skipped
    (see ``skipped_by_extension``) rather than filtering in silence.

Widening PROCESSABLE_IMAGE_EXTS is a live-verification job, not an
offline one - RealityScan's own import behaviour for TIFF/HEIF in this
build is not established here. Tracked in
testing/VERIFICATION_BACKLOG.md.
"""
from __future__ import annotations

import os
import hashlib
from pathlib import Path
import shutil

ALL_IMAGE_EXTS = frozenset({'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.heif'})

PROCESSABLE_IMAGE_EXTS = frozenset({'.jpg', '.jpeg', '.png', '.heif'})


def is_geometry_image(path: str | Path, accepted=ALL_IMAGE_EXTS) -> bool:
    """Masks are image layers, never independent cameras or flight-log rows."""
    path = Path(path)
    return (path.suffix.lower() in accepted and '.mask.' not in path.name.lower()
            and not any(part.lower() in ('.mask', '_mask') for part in path.parts[:-1]))


def associated_masks(image: str | Path) -> list[Path]:
    """Existing documented inline/folder mask layers for one geometry image."""
    image = Path(image)
    if not image.parent.is_dir():
        return []
    # Directory mtime on Windows may lag a new file, so it is not a safe cache
    # invalidator. Bounded exact-name probes stay linear without stale misses.
    candidates = {image.with_name(image.name + '.mask' + ext)
                  for ext in ALL_IMAGE_EXTS}
    for folder in (image.parent / '.mask', image.parent / '_mask'):
        if folder.is_dir():
            candidates.update(folder / (image.stem + ext) for ext in ALL_IMAGE_EXTS)
    return sorted(path for path in candidates if path.is_file())


def copy_associated_masks(image: str | Path, destination: str | Path) -> list[Path]:
    """Copy binary layers unchanged, normalized to image.ext.mask.ext naming."""
    destination = Path(destination)
    outputs = []
    for mask in associated_masks(image):
        target = destination.with_name(destination.name + '.mask' + mask.suffix.lower())
        if target.exists():
            with mask.open('rb') as source, target.open('rb') as existing:
                if hashlib.file_digest(source, 'sha256').digest() != hashlib.file_digest(existing, 'sha256').digest():
                    raise ValueError(f'Conflicting masks for {destination}')
        else:
            shutil.copy2(mask, target)
        outputs.append(target)
    return outputs


def skipped_by_extension(filenames, accepted) -> dict[str, int]:
    """{ext: count} of recognised imagery an ``accepted`` set excludes.

    Empty when nothing was dropped, so callers can do
    ``if skipped: logger.warning(...)`` and never emit a noise line on the
    normal path.
    """
    accepted = {e.lower() for e in accepted}
    out: dict[str, int] = {}
    for name in filenames:
        ext = os.path.splitext(str(name))[1].lower()
        if ext in ALL_IMAGE_EXTS and ext not in accepted:
            out[ext] = out.get(ext, 0) + 1
    return out
