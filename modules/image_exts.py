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

ALL_IMAGE_EXTS = frozenset({'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.heif'})

PROCESSABLE_IMAGE_EXTS = frozenset({'.jpg', '.jpeg', '.png', '.heif'})


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
