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


def build_fingerprint(flight_log: str | None,
                      flight_log_params: str | None,
                      align_settings_xml: str | None,
                      min_component_size: int,
                      rs_executable: str | None = None) -> dict:
    """Identity of everything that determines a zone's aligned output.

    align_settings_xml is the RS_ALIGN_PARAMS override when set, else the
    canonical Metadata/AlignmentParams.xml - i.e. whatever AlignZone.bat
    will actually apply.
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
