"""Per-zone alignment-input fingerprint (PRODUCT_READINESS must-fix 2).

One mechanism, three closures (persona + rigor audits, 2026-08-08):
- a RETRY after a settings/nav change was messaged identically to a
  same-settings retry - nothing on disk recorded which inputs built a
  component (align had no equivalent of the batcher's batch_inputs.json);
- resume logic (any driver's zone_done) was nav-blind: any .rsalign +
  .json = skip, even when the components were built from a superseded
  flight log (the two-frames incident class, C-20260805-01);
- merged deliverables carried no record of frame/settings unanimity
  across their input zones.

The fingerprint is written next to a zone's exported components as
``align_inputs.json`` after a successful align, and compared BEFORE a
re-run clears/supersedes the previous tree - so "you are retrying with
different inputs" is said out loud, with exactly what changed.

Identity is CONTENT (sha256), not path: a renamed-but-identical flight
log matches; an edited-in-place one does not.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time

from .flight_logs import utm_zone_from_flight_log_name

FINGERPRINT_NAME = "align_inputs.json"
SCHEMA = 1

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def sha256_file(path: str | None) -> str | None:
    if not path or not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _repo_sha() -> str | None:
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True,
            text=True, timeout=10, creationflags=_NO_WINDOW)
        return out.stdout.strip() or None if out.returncode == 0 else None
    except Exception:
        return None


def _file_identity(path: str | None) -> dict | None:
    """Path + content hash (+ size) for one input file; None when absent."""
    if not path or not os.path.isfile(path):
        return None
    return {"path": os.path.abspath(path),
            "sha256": sha256_file(path),
            "bytes": os.path.getsize(path)}


def file_identity(path: str | None) -> dict | None:
    """Public spelling of _file_identity for callers that add a provenance
    entry after the fingerprint was built (the prior-group command file is
    generated later in the align than the fingerprint)."""
    return _file_identity(path)


def xmp_export_shape(identity_dir: str | None) -> dict | None:
    """What the XMP harvest ACTUALLY wrote, as provenance.

    `-exportXMP` takes an optional params file and this repo has never
    passed one (rs-reference 09 sec.2.3), so the sidecar layout is whatever
    the instance's stored XMP export settings hold - where the CSV lane
    pins its format by GUID. There is no headless read-back of those
    settings, and reading them back would not prove they were honoured
    (rs-reference 03 sec.1.6/1.8), so the only honest record is the OUTPUT:
    the attribute set of a sidecar the run itself produced. Recorded, never
    compared - a different attribute set is a fact to notice, not a reason
    to refuse a retry.

    Returns {files, sample, attributes} or None when no harvest exists.
    """
    if not identity_dir or not os.path.isdir(identity_dir):
        return None
    names = sorted(f for f in os.listdir(identity_dir)
                   if f.lower().endswith(".xmp"))
    if not names:
        return None
    try:
        with open(os.path.join(identity_dir, names[0]),
                  encoding="utf-8", errors="replace") as fh:
            text = fh.read(65536)
    except OSError:
        return None
    attrs = sorted(set(re.findall(r"(xcr:[A-Za-z0-9_]+)", text)))
    return {"files": len(names), "sample": names[0], "attributes": attrs}


def build_fingerprint(flight_log: str | None,
                      flight_log_params: str | None,
                      align_settings_xml: str | None,
                      min_component_size: int,
                      rs_executable: str | None = None,
                      prior_groups: str | None = None) -> dict:
    """Identity of everything that determines a zone's aligned output.

    align_settings_xml is the RS_ALIGN_PARAMS override when set, else the
    canonical Metadata/AlignmentParams.xml - i.e. whatever AlignZone.bat
    will actually apply. prior_groups is the generated calibration/lens
    group command file AlignZone.bat replays (modules/prior_groups.py):
    PROVENANCE, recorded so a fingerprint says which grouping was asked
    for (the 2026-09-06 audit found nothing on disk did), but not a
    retry-changing input - it is a deterministic function of the images
    and cameras.json, so a change in it always comes with a change in one
    of the compared fields.
    """
    frame = ("utm" if (flight_log and utm_zone_from_flight_log_name(flight_log))
             else "local_euclidean")
    fp = {
        "schema": SCHEMA,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "frame": frame,
        "flight_log": _file_identity(flight_log),
        "flight_log_params": _file_identity(flight_log_params),
        "align_settings": _file_identity(align_settings_xml),
        "prior_groups": _file_identity(prior_groups),
        "identity_capture": ("csv" if os.environ.get(
            "RS_LEGACY_XMP_IDENTITY") == "0" else "xmp"),
        "min_component_size": int(min_component_size),
        "repo_sha": _repo_sha(),
    }
    if rs_executable and os.path.isfile(rs_executable):
        st = os.stat(rs_executable)
        fp["realityscan"] = {"path": os.path.abspath(rs_executable),
                             "bytes": st.st_size,
                             "mtime": time.strftime(
                                 "%Y-%m-%d %H:%M:%S",
                                 time.localtime(st.st_mtime))}
    return fp


# What changed between two fingerprints, in operator language. Keyed by
# the science-relevant identity, not incidental fields (created/repo_sha
# alone do not make a retry "different").
_COMPARED = (
    ("flight_log", "navigation flight log (positions/orientations)"),
    ("flight_log_params", "coordinate-frame template (FlightLogParams)"),
    ("align_settings", "alignment settings XML (detector/priors/model)"),
)

#: Fields compared ACROSS zones by modules.verify but not between a zone's
#: own runs: the identity mechanism decides which membership record exists
#: and whether sidecars were written beside the images, so zones captured
#: differently are not comparable - but re-aligning one zone with the other
#: mechanism is a deliberate act, not a "changed inputs" surprise.
_CROSS_ZONE_ONLY = (
    ("identity_capture", "identity capture mechanism (csv / xmp)"),
)


def diff_fingerprints(old: dict | None, new: dict) -> list[str]:
    """Human-readable list of MATERIAL input changes (empty = same run
    inputs). Content-hash comparison; path changes with identical content
    are reported as informational, not material."""
    if not old:
        return []
    changes = []
    for key, label in _COMPARED:
        o, n = old.get(key), new.get(key)
        osha = o.get("sha256") if isinstance(o, dict) else None
        nsha = n.get("sha256") if isinstance(n, dict) else None
        if osha != nsha:
            changes.append(
                f"{label} CHANGED: {osha or 'absent'} -> {nsha or 'absent'}"
                + (f" (now {n['path']})" if isinstance(n, dict) else ""))
    if old.get("frame") != new.get("frame"):
        changes.append(f"coordinate FRAME changed: {old.get('frame')} -> "
                       f"{new.get('frame')} - never merge across frames")
    if old.get("min_component_size") != new.get("min_component_size"):
        changes.append(
            f"min_component_size changed: {old.get('min_component_size')} -> "
            f"{new.get('min_component_size')} (export threshold; small "
            "pockets appear/disappear)")
    return changes


def write_fingerprint(out_dir: str, fp: dict) -> str:
    path = os.path.join(out_dir, FINGERPRINT_NAME)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(fp, fh, indent=2)
    os.replace(tmp, path)
    return path


def read_fingerprint(out_dir: str) -> dict | None:
    path = os.path.join(out_dir, FINGERPRINT_NAME)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def matches_current(out_dir: str, current: dict) -> bool:
    """True iff out_dir holds a fingerprint whose MATERIAL identity equals
    `current` - the nav-aware resume test (a zone is 'done' only when its
    components were built from the same nav + frame + settings)."""
    old = read_fingerprint(out_dir)
    return bool(old) and not diff_fingerprints(old, current)
