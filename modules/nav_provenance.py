"""Navigation-table provenance: is ONE nav table behind every aligned zone?

modules.verify compared each zone's ``align_inputs.json`` ``flight_log``
sha256 across zones - but in any batched dive that file is a per-zone ROW
SUBSET written by image_batcher.batch_directory.__create_batch_folders, so
H2060's nine zones legitimately carry nine different hashes and the guard
reported the run as the two-frames incident class (C-20260805-01) it
exists to catch. Measured 2026-09-19: every batched dive on this machine
(H2060, H2082) trips it. A guard that fires on 100% of a class carries no
information about which member of it is faulted, and the only operator
response left is to route around the oracle.

The identity that answers the merge question is not the file the aligner
was handed, it is the nav TABLE behind it: do the rows agree. Everything
here is measured from bytes on disk. ``batch_inputs.json`` is used only to
NAME a candidate - a file must HASH to the recorded value before one row
of it is read - so a stale or hand-written marker can only fail to
resolve, never manufacture a pass.

Four normalizations are mandatory, and all four were MEASURED on H2060 and
H2082 rather than assumed:

  - the georeference master carries a UTF-8 BOM and calls column 0
    ``Name``; the batcher's pandas round trip strips the BOM and renames
    column 0 to ``filename`` (batch_directory.py:1021-1023);
  - line terminators are written with the local convention at write time,
    not copied from the master, so terminators are never compared;
  - pool layout rewrites column 0 to the absolute canonical image path, so
    column 0 is matched as a path SUFFIX - never reduced to a bare
    basename, which would make C:\\poolA\\wca\\DSC1.JPG and
    C:\\poolB\\wca\\DSC1.JPG the same row and re-open the split-identity
    defect pool layout exists to fix;
  - pandas writes QUOTE_MINIMAL, so a row that differs literally is
    re-compared field by field before it is called a difference.

Across 34,877 H2060 slice rows and 5,479 H2082 slice rows, zero differ
from their master row under those rules - the pandas round trip preserves
data rows exactly. Only the header legitimately differs.

Decoding is STRICT. ``errors="replace"`` maps two different undefined
bytes onto one U+FFFD, which would make two different rows compare EQUAL
inside an equality proof.

Nothing here decides a verdict. It returns measurements, ``findings``
(something was measured and it is wrong) and ``unavailable`` (it could not
be measured). modules.verify blocks on both: absence of evidence is never
unanimity.
"""
from __future__ import annotations

import csv
import hashlib
import os
from pathlib import Path

from .workspace_census import IMAGE_EXTS

BATCHED_DIR_NAME = "batched_images_by_zone"

#: Directory names whose flight logs are DERIVED from the zone slices, or
#: are superseded copies of them. merge_zones' union log is built FROM the
#: slices and resolves cross-zone conflicts silently (first row seen wins),
#: so a union cannot witness an agreement it has already discarded.
#: Proving a slice against one is circular. H2063 carries exactly such a
#: look-alike: merged_v3\\assembly\\ holds the same basename its
#: batch_inputs.json names.
_DERIVED_PARTS = {BATCHED_DIR_NAME, "assembly", "superseded", "archive"}

#: Hard cap on files hashed while hunting for an anchor, so a wide search
#: on a NAS cannot turn verify into a scan.
MAX_ANCHOR_CANDIDATES = 400


def sha256_file(path: str | None) -> str | None:
    """Content hash of one file, None when it is not there."""
    if not path or not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def nav_key(field0: str) -> tuple[str, ...]:
    """Column 0 as lowercased path segments.

    Column 0 is the only field saying WHICH image a row describes, so it
    never leaves the comparison; it is matched as a path suffix instead,
    because the batcher rewrites it to an absolute path in pool layout
    while the master holds the georeference module's relative name.
    """
    text = field0.strip().strip('"').replace("\\", "/")
    return tuple(p.lower() for p in text.split("/") if p not in ("", "."))


def _split_row(line: str) -> tuple[tuple[str, ...], str]:
    field0, _sep, tail = line.partition(";")
    return nav_key(field0), tail


def read_nav(path: str | os.PathLike) -> dict:
    """One nav table as {header, rows:[(key, tail)]}, or an ``error``."""
    out = {"path": str(path), "header": "", "rows": [], "encoding": None,
           "error": None}
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        out["error"] = "cannot be read (%s)" % exc
        return out
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    text = None
    for enc in ("utf-8", "cp1252"):
        try:
            text = raw.decode(enc)
            out["encoding"] = enc
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        # The georeference master is written with a bare open(), i.e. the
        # locale codepage, so cp1252 is tried - but a file that decodes as
        # NEITHER is unreadable evidence, not evidence of sameness.
        out["error"] = "is not decodable as utf-8 or cp1252"
        return out
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        out["error"] = "is empty"
        return out
    out["header"] = lines[0]
    out["rows"] = [_split_row(ln) for ln in lines[1:]]
    return out


def same_row(a: str, b: str) -> bool:
    """Literal equality, else field by field.

    pandas writes QUOTE_MINIMAL, so a master field that arrived
    redundantly quoted comes back unquoted in the slice. That is a
    serialization difference, not a navigation one. Anything else is a
    difference.
    """
    if a == b:
        return True
    try:
        return (next(csv.reader([a], delimiter=";"))
                == next(csv.reader([b], delimiter=";")))
    except (csv.Error, StopIteration):
        return False


def columns_compatible(master_header: str, zone_header: str) -> bool:
    """Same columns after column 0's Name -> filename rename."""
    m = [c.strip().lower() for c in master_header.split(";")]
    z = [c.strip().lower() for c in zone_header.split(";")]
    return len(m) > 1 and len(z) > 1 and m[1:] == z[1:]


def index_rows(rows) -> tuple[dict, dict, set]:
    """(by_full, by_base, conflicts) for one table.

    ONE tail per key. A table naming an image twice with DIFFERENT
    navigation is satisfied by both solutions at once, so it cannot
    witness that the zones agree - that key goes to ``conflicts`` and the
    caller refuses. Nothing upstream enforces uniqueness: the batcher's
    set_index permits duplicates, and its collision guard raises only when
    two DIFFERENT raw paths collapse to one basename.
    """
    by_full: dict[tuple, str] = {}
    by_base: dict[str, list[tuple]] = {}
    conflicts: set = set()
    for key, tail in rows:
        if not key:
            continue
        if key in by_full:
            if not same_row(by_full[key], tail):
                conflicts.add(key)
            continue
        by_full[key] = tail
        by_base.setdefault(key[-1], []).append(key)
    return by_full, by_base, conflicts


def match_key(key, by_full, by_base) -> tuple[tuple | None, str]:
    """(table key, how) for one slice row: exact | suffix | ambiguous | absent.

    Suffix matching runs in BOTH directions: the slice row may carry an
    absolute pool path against a master's relative ``wca/DSC1.JPG``, or a
    bare basename against a master that carries the camera subfolder. Two
    table rows a slice key could equally name is a NAMING COLLISION,
    reported as unverified - never as a nav disagreement, which would send
    an operator hunting a fault that does not exist.
    """
    if key in by_full:
        return key, "exact"
    cands = by_base.get(key[-1], []) if key else []
    suffix = [c for c in cands
              if (len(c) <= len(key) and key[-len(c):] == c)
              or (len(key) <= len(c) and c[-len(key):] == key)]
    if len(suffix) == 1:
        return suffix[0], "suffix"
    if len(suffix) > 1:
        return None, "ambiguous"
    return None, "absent"


def compare_slice(by_full, by_base, conflicts, zrows) -> dict:
    """One slice's rows against an indexed table."""
    out = {"rows": len(zrows), "absent": 0, "differing": 0, "ambiguous": 0,
           "matched": 0}
    for key, tail in zrows:
        mkey, how = match_key(key, by_full, by_base)
        if how == "ambiguous" or (mkey is not None and mkey in conflicts):
            out["ambiguous"] += 1
            continue
        if mkey is None:
            out["absent"] += 1
            continue
        out["matched"] += 1
        if not same_row(by_full[mkey], tail):
            out["differing"] += 1
    return out


#: What the batcher will actually put in a zone. Narrower than the
#: census's IMAGE_EXTS on purpose: a .tif/.heif dataset is recognised
#: imagery elsewhere in the pipeline but is never batched, so counting it
#: here would accuse a zone of holding imagery its flight log "missed".
BATCHED_IMAGE_EXTS = {".png", ".jpg", ".jpeg"}


def zone_image_keys(zone_dir) -> tuple[set | None, str]:
    """(nav keys of the images this zone holds, layout), None when unknown.

    Used to size a containment proof: a header-only or truncated slice is
    contained in EVERY table and proves nothing, and header-only is a
    reachable production state (pool layout writes one when no row
    resolves).

    Counting is NOT the test - an exact row-to-image equality blocked
    H2082, whose zone_1 legitimately holds 180 images (00000.jpeg ...)
    that appear in no flight log at all, its own master included
    (measured 2026-09-19). Images carrying no navigation are a real
    condition and not this guard's business. The caller asks the sharper
    question instead: of the images with no row, how many does the TABLE
    have a row for? Those, and only those, are a slice cut short of its
    own source.
    """
    root = Path(zone_dir)
    if not root.is_dir():
        return None, "unknown"
    lists = sorted(root.glob("*.imagelist"))
    if lists:
        try:
            text = lists[0].read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None, "pool"
        return ({nav_key(ln) for ln in text.splitlines() if ln.strip()},
                "pool")
    keys = set()
    for dirpath, _sub, files in os.walk(root):
        for f in files:
            if Path(f).suffix.lower() in BATCHED_IMAGE_EXTS:
                keys.add(nav_key(str(Path(dirpath).name) + "/" + f))
    return keys, "copy"


def is_derived_nav(path) -> bool:
    """True for a per-zone slice, a merge union, or a superseded copy."""
    p = Path(path)
    if {seg.lower() for seg in p.parts} & _DERIVED_PARTS:
        return True
    return ((p.parent / "merge_report.json").is_file()
            or (p.parent.parent / "merge_report.json").is_file())


def _walk_logs(root: Path, max_depth: int):
    base = len(root.parts)
    for dirpath, dirnames, files in os.walk(root):
        if len(Path(dirpath).parts) - base >= max_depth:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames
                       if d.lower() not in _DERIVED_PARTS
                       and not d.startswith(".")]
        for name in files:
            low = name.lower()
            if low.startswith("flight_log") and low.endswith(".txt"):
                yield Path(dirpath) / name


def find_by_sha(roots, wanted_sha: str, max_depth: int = 3) -> list[str]:
    """Every non-derived flight log under ``roots`` hashing to ``wanted_sha``.

    Selection is by CONTENT, never by name, so the search can be wide
    without being able to mis-bind: a file either hashes to the anchor or
    it does not. It has to be wide - H2063's master lives OUTSIDE its
    workspace, and a name-based search would instead bind to
    merged_v3\\assembly\\, a union built from the very slices under test.
    """
    hits: list[str] = []
    seen: set = set()
    scanned = 0
    for root in roots:
        root = Path(root) if root else None
        if not root or not root.is_dir():
            continue
        for path in _walk_logs(root, max_depth):
            real = os.path.normcase(os.path.abspath(path))
            if real in seen or is_derived_nav(path):
                continue
            seen.add(real)
            scanned += 1
            if scanned > MAX_ANCHOR_CANDIDATES:
                return hits
            if sha256_file(str(path)) == wanted_sha:
                hits.append(str(path))
    return hits


def pairwise_agreement(zone_logs: dict) -> dict:
    """Do overlapping zones carry identical rows for their shared images?

    Independent of any master, any marker and any root argument - it reads
    only the slices the fingerprints already name. It cannot stand alone
    (two zones with no overlap have nothing to disagree about), so verify
    reports it rather than gating on it. It is the measurement that
    survives losing the master: on H2060 the nine zones share 5,816 rows
    and the overlap graph is connected, so agreement there alone shows one
    nav solution behind all nine.
    """
    out = {"zones": len(zone_logs), "shared_keys": 0, "conflicts": 0,
           "examples": [], "errors": []}
    seen: dict = {}
    for zone in sorted(zone_logs):
        log = read_nav(zone_logs[zone])
        if log["error"]:
            out["errors"].append("%s: %s" % (zone, log["error"]))
            continue
        for key, tail in log["rows"]:
            if not key:
                continue
            prev = seen.get(key)
            if prev is None:
                seen[key] = (zone, tail)
                continue
            out["shared_keys"] += 1
            if not same_row(prev[1], tail):
                out["conflicts"] += 1
                if len(out["examples"]) < 5:
                    out["examples"].append(
                        "%s differs between %s and %s"
                        % ("/".join(key), prev[0], zone))
    return out
