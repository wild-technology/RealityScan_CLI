"""Versioned, data-only project documents for human-operated frontends.

This is persistence and lifecycle bookkeeping, not a science planner or runner.
Creation, loading and lifecycle edits are in memory; only save/create_layout write.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import ntpath
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import tempfile
from datetime import datetime, timezone
from uuid import UUID, uuid4


SCHEMA = 1
STAGES = ("inventory", "navigation", "georeference", "preprocess", "batch", "align", "merge",
          "model", "export")
STATES = frozenset(("pending", "running", "succeeded", "failed", "interrupted",
                    "invalidated", "skipped"))
LAYOUT = {"raw": "raw", "proc": "proc", "tmp": "proc/tmp", "logs": "logs",
          "metadata": "metadata"}
MAX_DOCUMENT_BYTES = 16 * 1024 * 1024


class ProjectError(ValueError):
    """Invalid project data, unsafe path, or illegal lifecycle transition."""


class ProjectConflictError(ProjectError):
    """Saving would overwrite an unrelated or externally changed document."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ProjectError(message)


def _text(value, where: str) -> None:
    _check(isinstance(value, str) and bool(value.strip()), f"{where}: nonempty string required")


def settings_stage(block: str) -> str | None:
    """Earliest science stage affected by a settings block.

    Operating/budget values govern future execution checks, not existing science
    products. Their approvals still expire when those values change. Unknown
    blocks conservatively invalidate from inventory; callers can explicitly
    override the scope through set_settings(affects_stage=...).
    """
    _text(block, 'settings block')
    if block in ('operating', 'budget'):
        return None
    if block == 'science':
        return 'align'
    if block == 'cameras':
        return 'georeference'
    return block if block in STAGES else 'inventory'


def _uuid(value, where: str) -> None:
    _text(value, where)
    try:
        _check(str(UUID(value)) == value, f"{where}: canonical UUID required")
    except ValueError as exc:
        raise ProjectError(f"{where}: invalid UUID") from exc


def _time(value, where: str) -> None:
    _text(value, where)
    try:
        _check(datetime.fromisoformat(value).utcoffset() is not None,
               f"{where}: timezone required")
    except ValueError as exc:
        raise ProjectError(f"{where}: invalid timestamp") from exc


def _keys(value, keys: str, where: str) -> None:
    _check(type(value) is dict and set(value) == set(keys.split()),
           f"{where}: expected fields {keys}")


def _json_value(value, depth: int = 0) -> None:
    _check(depth <= 64, "JSON nesting exceeds 64 levels")
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        _check(math.isfinite(value), "JSON numbers must be finite")
    elif type(value) is list:
        for item in value:
            _json_value(item, depth + 1)
    elif type(value) is dict:
        for key, item in value.items():
            _check(type(key) is str, "JSON object keys must be strings")
            _json_value(item, depth + 1)
    else:
        raise ProjectError(f"Not JSON data: {type(value).__name__}")


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _hash(value, where: str) -> None:
    _check(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
           f"{where}: SHA-256 required")


def _absolute(value: str | Path) -> Path:
    _text(str(value), "path")
    text = str(value)
    # Reject Windows aliases/streams/device paths even when inspecting on POSIX.
    _check(not text.startswith(("\\\\?\\", "\\\\.\\")), "Device paths are forbidden")
    parts = PureWindowsPath(text).parts
    for part in parts[1:] if PureWindowsPath(text).anchor else parts:
        _check(not any(c in part for c in '<>:"|?*') and
               not any(ord(c) < 32 for c in part), "Unsafe path component")
        _check(part not in (".", "..") and not part.endswith((" ", ".")),
               "Path aliases and traversal are forbidden")
        _check(not ntpath.isreserved(part), "Reserved Windows path name")
    path = Path(value)
    _check(path.is_absolute(), f"Absolute native path required: {value}")
    try:
        return path.resolve()
    except (OSError, RuntimeError) as exc:
        raise ProjectError(f"Cannot resolve path: {value}") from exc


def _contains(parent: Path, child: Path) -> bool:
    # Resolve junctions/symlinks before reusing the charter's Windows comparison.
    from .run_charter import _contains as charter_contains
    return charter_contains(parent.resolve(), child.resolve())


def _relative(value: str) -> None:
    _text(value, "relative path")
    path = PureWindowsPath(value)
    _check(not path.anchor and "\\" not in value and
           all(p not in ("", ".", "..") for p in value.split("/")),
           "Expected normalized root-relative path")


def _read(path: Path) -> bytes:
    with path.open("rb") as stream:
        raw = stream.read(MAX_DOCUMENT_BYTES + 1)
    _check(len(raw) <= MAX_DOCUMENT_BYTES, "Project document exceeds size limit")
    return raw


def _decode(raw: bytes) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _check(key not in result, f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ProjectError(f"Invalid project JSON: {exc}") from exc


class ProjectDocument:
    """Mutable in-memory document; public snapshots never alias internal data."""

    def __init__(self, data: dict):
        _json_value(data)
        self._data = copy.deepcopy(data)
        self._path: Path | None = None
        self._disk_hash: str | None = None
        self.recovered_from_backup = False
        self._validate()
        if self._invalidate_approvals():
            # External edits have no known earliest affected stage. Keep active
            # attempts running until explicit recovery, but retire cached results.
            for stage in self._data["stages"].values():
                if stage["state"] not in ("pending", "running"):
                    stage.update(state="invalidated", reason="Approval content changed")
            for output in self._data["outputs"]:
                output["valid"] = False

    @classmethod
    def create(cls, expedition: str, dive: str, root: str | Path,
               sources=()) -> ProjectDocument:
        """Create data only. Sources are explicit read-only files or directories."""
        _check(not isinstance(sources, (str, bytes, Path)), "sources must be a sequence of paths")
        now = _now()
        return cls({"format": "rovscan", "schema": SCHEMA, "id": str(uuid4()),
                    "expedition": expedition, "dive": dive, "root": str(_absolute(root)),
                    "sources": [str(_absolute(p)) for p in sources], "layout": dict(LAYOUT),
                    "created_at": now, "updated_at": now, "settings": {},
                    "stages": {name: {"state": "pending", "attempts": [], "reason": ""}
                               for name in STAGES}, "outputs": []})

    @classmethod
    def load(cls, path: str | Path, *, recover_backup: bool = False) -> ProjectDocument:
        """Read without repairs/writes. Backup fallback is an explicit opt-in."""
        path = _absolute(path)
        _check(path.suffix.lower() == ".rovscan", "Project extension must be .rovscan")
        raw = None
        try:
            raw = _read(path)
            document = cls(_decode(raw))
            document._document_path(path)
        except (OSError, ProjectError) as primary_error:
            if not recover_backup:
                raise ProjectError(f"Cannot open {path}: {primary_error}") from primary_error
            try:
                document = cls(_decode(_read(cls.backup_path(path))))
                document._document_path(path)
                document._document_path(cls.backup_path(path), backup=True)
            except (OSError, ProjectError) as backup_error:
                raise ProjectError(f"Primary and backup unavailable: {primary_error}; "
                                   f"{backup_error}") from backup_error
            document.recovered_from_backup = True
        document._path = path
        document._disk_hash = hashlib.sha256(raw).hexdigest() if raw is not None else None
        return document

    @staticmethod
    def backup_path(path: str | Path) -> Path:
        return Path(str(path) + ".bak")

    @property
    def root(self) -> Path:
        return Path(self._data["root"])

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def project_id(self) -> str:
        return self._data["id"]

    @property
    def settings_hash(self) -> str:
        """Whole-project attempt provenance; preserves the legacy hash algorithm.

        Settings approvals use per-block settings_signature instead. Historical
        attempt hashes never change when another block is edited or migrated.
        """
        return _digest({key: self._data[key] for key in
                        ("schema", "id", "expedition", "dive", "root", "sources", "layout")} |
                       {"settings": {key: block["values"]
                                     for key, block in self._data["settings"].items()}})

    def settings_signature(self, blocks) -> str:
        """Hash explicit block values plus project/path identity, independent of others.

        Names are order-independent and must be unique. An absent named block is
        encoded as null, distinct from a present block with empty values. This
        supports optional stage settings without claiming they were approved.
        Approval metadata/timestamps are never inputs to either settings hash.
        """
        _check(not isinstance(blocks, (str, bytes)) and blocks is not None,
               'blocks must be a sequence of names')
        try:
            names = list(blocks)
        except TypeError as exc:
            raise ProjectError('blocks must be a sequence of names') from exc
        for name in names:
            _text(name, 'settings signature block')
        _check(len(names) == len(set(names)), 'Duplicate settings signature block')
        identity = {key: self._data[key] for key in
                    ('schema', 'id', 'expedition', 'dive', 'root', 'sources', 'layout')}
        values = {name: self._data['settings'][name]['values']
                  if name in self._data['settings'] else None for name in sorted(names)}
        return _digest(dict(scope='project-settings-subset-v1', project=identity, blocks=values))

    def to_dict(self) -> dict:
        return copy.deepcopy(self._data)

    def resolve_path(self, path: str | Path) -> Path:
        """Resolve an output path; reject escapes and source intersections."""
        if not Path(path).is_absolute():
            _relative(str(path))
            path = self.root / path
        resolved = _absolute(path)
        _check(_contains(self.root, resolved), f"Path outside project root: {path}")
        for source in self._data["sources"]:
            source_path = _absolute(source)
            _check(not _contains(source_path, resolved) and not _contains(resolved, source_path),
                   f"Path overlaps read-only source: {source}")
        return resolved

    def _document_path(self, path: Path, *, backup: bool = False) -> Path:
        _check(path.name.lower().endswith(".rovscan.bak" if backup else ".rovscan"),
               "Invalid document extension")
        resolved = self.resolve_path(path)
        if path.exists():
            _check(path.is_file() and not path.is_symlink() and path.stat().st_nlink == 1,
                   "Document must be a regular, unlinked file")
        _check(not any(resolved == self.resolve_path(item["path"])
                       for item in self._data["outputs"]), "Document conflicts with a deliverable")
        return resolved

    def _validate(self) -> None:
        d = self._data
        _keys(d, "format schema id expedition dive root sources layout created_at updated_at "
              "settings stages outputs", "project")
        _check(d["format"] == "rovscan" and type(d["schema"]) is int and d["schema"] == SCHEMA,
               "Unsupported project format/schema")
        _uuid(d["id"], "id")
        for key, pattern in (("expedition", r"NA[0-9]{3}"), ("dive", r"H[0-9]{4}")):
            _check(isinstance(d[key], str) and re.fullmatch(pattern, d[key]) is not None,
                   f"Invalid {key}")
        _text(d["root"], "root")
        root = _absolute(d["root"])
        _check(root.parent != root, "Project root cannot be a volume root")
        _check(type(d["sources"]) is list, "sources must be a list")
        source_keys = set()
        for source in d["sources"]:
            _text(source, "source")
            p = _absolute(source)
            key = os.path.normcase(str(p))
            _check(key not in source_keys, "Duplicate source path")
            source_keys.add(key)
            _check(not _contains(p, root) and not _contains(root, p),
                   "Project root and read-only source overlap")
        _check(d["layout"] == LAYOUT, "Unsupported project layout")
        for value in LAYOUT.values():
            self.resolve_path(value)
        _time(d["created_at"], "created_at")
        _time(d["updated_at"], "updated_at")
        _check(type(d["settings"]) is dict, "settings must be an object")
        for name, block in d["settings"].items():
            _text(name, "settings block name")
            _keys(block, "values approval", f"settings.{name}")
            _check(type(block["values"]) is dict, "settings values must be an object")
            approval = block["approval"]
            if approval is not None:
                _keys(approval, "content_hash by at", "approval")
                _hash(approval["content_hash"], "approval hash")
                _text(approval["by"], "approval by")
                _time(approval["at"], "approval at")
        _keys(d["stages"], " ".join(STAGES), "stages")
        attempts = {}
        running = 0
        for name, stage in d["stages"].items():
            _keys(stage, "state attempts reason", f"stage {name}")
            _check(isinstance(stage["state"], str) and stage["state"] in STATES, "Invalid stage state")
            _check(isinstance(stage["reason"], str) and type(stage["attempts"]) is list,
                   "Invalid stage reason/attempts")
            for number, attempt in enumerate(stage["attempts"], 1):
                _keys(attempt, "id number state started_at ended_at settings_hash message", "attempt")
                _uuid(attempt["id"], "attempt id")
                _check(attempt["id"] not in attempts, "Duplicate attempt id")
                attempts[attempt["id"]] = name
                _check(type(attempt["number"]) is int and attempt["number"] == number,
                       "Attempt numbers must be consecutive")
                _check(attempt["state"] in ("running", "succeeded", "failed", "interrupted"),
                       "Invalid attempt state")
                _time(attempt["started_at"], "attempt started_at")
                _hash(attempt["settings_hash"], "attempt settings_hash")
                _check(isinstance(attempt["message"], str), "Invalid attempt message")
                if attempt["state"] == "running":
                    running += 1
                    _check(number == len(stage["attempts"]) and stage["state"] == "running"
                           and attempt["ended_at"] is None, "Inconsistent running attempt")
                else:
                    _time(attempt["ended_at"], "attempt ended_at")
                    _check(datetime.fromisoformat(attempt["ended_at"]) >=
                           datetime.fromisoformat(attempt["started_at"]),
                           "Attempt ends before it starts")
            if stage["state"] in ("running", "succeeded", "failed", "interrupted"):
                _check(bool(stage["attempts"]) and stage["attempts"][-1]["state"] == stage["state"],
                       "Stage and latest attempt disagree")
            if stage["state"] == "pending":
                _check(not stage["attempts"], "Pending stage cannot have attempts")
            if stage["state"] in ("running", "succeeded", "skipped"):
                self._predecessors(name)
            _check(name != "preprocess" or stage["state"] != "skipped",
                   "Preprocess review is mandatory and cannot be skipped")
        _check(running <= 1, "Only one stage may be running")
        _check(type(d["outputs"]) is list, "outputs must be a list")
        paths = set()
        for output in d["outputs"]:
            _keys(output, "path stage attempt_id sha256 bytes mtime_ns recorded_at valid", "output")
            _relative(output["path"])
            resolved = self.resolve_path(output["path"])
            key = os.path.normcase(str(resolved))
            _check(key not in paths, "Duplicate output path")
            paths.add(key)
            _text(output["attempt_id"], "output attempt id")
            _check(output["attempt_id"] in attempts and
                   attempts[output["attempt_id"]] == output["stage"], "Output attempt/stage mismatch")
            _hash(output["sha256"], "output sha256")
            for field in ("bytes", "mtime_ns"):
                _check(type(output[field]) is int and output[field] >= 0, f"Invalid output {field}")
            _time(output["recorded_at"], "output recorded_at")
            _check(type(output["valid"]) is bool, "Output valid must be boolean")
            if output["valid"]:
                stage = d["stages"][output["stage"]]
                _check(stage["state"] in ("running", "succeeded") and
                       stage["attempts"][-1]["id"] == output["attempt_id"],
                       "Current output does not belong to the current running/succeeded attempt")

    def _invalidate_approvals(self) -> bool:
        """Migrate only proven current legacy approvals, preserving signer/time.

        Called on construction and BEFORE any settings value mutation. Exact
        equality to the current old whole-project hash proves the legacy scope;
        no old values are inferred. A mismatch against both scopes is revoked.
        Migration changes in-memory approval hashes only, never files or attempts.
        """
        legacy_hash = self.settings_hash
        invalidated = False
        for name, block in self._data["settings"].items():
            approval = block['approval']
            if approval:
                block_hash = self.settings_signature([name])
                if approval['content_hash'] == legacy_hash:
                    approval['content_hash'] = block_hash
                elif approval['content_hash'] != block_hash:
                    block['approval'] = None
                    invalidated = True
        return invalidated

    def _touch(self) -> None:
        self._data["updated_at"] = _now()

    def create_layout(self) -> dict[str, Path]:
        """Explicitly create the fixed empty workspace layout; never called by Open."""
        self._validate()
        paths = {name: self.resolve_path(value) for name, value in LAYOUT.items()}
        for path in paths.values():
            _check(not path.exists() or path.is_dir(), f"Layout path is not a directory: {path}")
        for path in paths.values():
            self.resolve_path(path).mkdir(parents=True, exist_ok=True)
        return paths

    def save(self, path: str | Path | None = None) -> Path:
        """Atomically replace JSON, keeping the previous valid revision in .bak.

        Reject stale writers and unrelated destinations. The caller serializes
        concurrent saves (e.g. its GUI controller); this is not a process lock.
        """
        self._validate()
        self._invalidate_approvals()
        target = _absolute(path) if path is not None else self._path
        if target is None:
            target = self.root / f"{self._data['expedition']}_{self._data['dive']}.rovscan"
        target = self._document_path(target)
        backup = self._document_path(self.backup_path(target), backup=True)
        existing = _read(target) if target.exists() else None
        token = hashlib.sha256(existing).hexdigest() if existing is not None else None
        if target == self._path:
            if token != self._disk_hash:
                raise ProjectConflictError("Project changed on disk; reload before saving")
        elif existing is not None or backup.exists():
            raise ProjectConflictError("Save destination already exists; choose a new name")
        previous_valid = False
        if existing is not None:
            try:
                old = type(self)(_decode(existing))
                previous_valid = old.project_id == self.project_id
            except ProjectError:
                pass
            _check(previous_valid or self.recovered_from_backup,
                   "Refusing to overwrite invalid project without explicit recovery")
        raw = (json.dumps(self._data, ensure_ascii=True, sort_keys=True, indent=2,
                          allow_nan=False) + "\n").encode("utf-8")
        _check(len(raw) <= MAX_DOCUMENT_BYTES, "Project document exceeds size limit")
        target.parent.mkdir(parents=True, exist_ok=True)
        if previous_valid:
            self._atomic_write(backup, existing)
        self._atomic_write(target, raw)
        self._path = target
        self._disk_hash = hashlib.sha256(raw).hexdigest()
        self.recovered_from_backup = False
        return target

    def _atomic_write(self, target: Path, raw: bytes) -> None:
        self.resolve_path(target)
        fd, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            self.resolve_path(target)
            from module_base.atomic_io import replace_file
            replace_file(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def _idle(self) -> None:
        _check(not any(s["state"] == "running" for s in self._data["stages"].values()),
               "A stage is running; finish it or explicitly recover it first")

    def _stage(self, name: str) -> dict:
        _check(isinstance(name, str) and name in STAGES, f"Unknown stage: {name}")
        return self._data["stages"][name]

    def _invalidate_from(self, name: str, reason: str) -> None:
        affected = STAGES[STAGES.index(name):]
        for stage_name in affected:
            stage = self._stage(stage_name)
            if stage["state"] != "pending":
                stage["state"] = "invalidated"
            stage["reason"] = reason
        for output in self._data["outputs"]:
            if output["stage"] in affected:
                output["valid"] = False

    def set_settings(self, block: str, values: dict, *, affects_stage: str | None = None) -> None:
        """Replace one block, revoke its approval, and invalidate its mapped stages.

        Explicit affects_stage overrides the shared dependency map. Execution-only
        operating/budget edits retain every completed science stage. Valid legacy
        approvals are migrated against the OLD global hash before changing values.
        """
        self._idle()
        _text(block, "settings block")
        if affects_stage is not None:
            self._stage(affects_stage)
        _check(type(values) is dict, "Settings values must be an object")
        _json_value(values)
        if self._invalidate_approvals():
            # Unattributable external edits remain conservative, unlike a normal
            # value mutation whose block and dependency scope are known here.
            self._invalidate_from('inventory', 'Approval content changed')
        old = self._data["settings"].get(block)
        if old is not None and _digest(old["values"]) == _digest(values):
            return
        self._data["settings"][block] = {"values": copy.deepcopy(values), "approval": None}
        stage = affects_stage if affects_stage is not None else settings_stage(block)
        if stage is not None:
            self._invalidate_from(stage, 'Settings changed')
        self._touch()

    def approve_settings(self, block: str, approved_by: str) -> str:
        """Record explicit approval for this block's current project-bound values."""
        _text(approved_by, "approved_by")
        _check(block in self._data["settings"], f"Unknown settings block: {block}")
        digest = self.settings_signature([block])
        self._data["settings"][block]["approval"] = {
            "content_hash": digest, "by": approved_by, "at": _now()}
        self._touch()
        return digest

    def settings_approved(self, required_blocks=None) -> bool:
        """Whether every requested block has its own current content approval."""
        names = self._data["settings"] if required_blocks is None else required_blocks
        _check(not isinstance(names, (str, bytes)), "required_blocks must be a sequence of names")
        blocks = []
        for name in names:
            _text(name, "required settings block")
            if name not in self._data["settings"]:
                return False
            blocks.append((name, self._data["settings"][name]))
        return all(block["approval"] and block["approval"]["content_hash"] == self.settings_signature([name])
                   for name, block in blocks)

    def _predecessors(self, name: str) -> None:
        self._stage(name)
        for predecessor in STAGES[:STAGES.index(name)]:
            _check(self._stage(predecessor)["state"] in ("succeeded", "skipped"),
                   f"Predecessor {predecessor} is not completed or explicitly skipped")

    def start_stage(self, stage: str, *, required_blocks=None) -> str:
        self._validate()
        entry = self._stage(stage)
        self._idle()
        self._predecessors(stage)
        _check(self.settings_approved(required_blocks), "Settings require approval")
        _check(entry["state"] in ("pending", "invalidated"), "Restart the stage before retrying")
        attempt_id = str(uuid4())
        entry["attempts"].append({"id": attempt_id, "number": len(entry["attempts"]) + 1,
                                  "state": "running", "started_at": _now(), "ended_at": None,
                                  "settings_hash": self.settings_hash, "message": ""})
        entry["state"], entry["reason"] = "running", ""
        self._touch()
        return attempt_id

    def _active(self, stage: str, attempt_id: str) -> dict:
        entry = self._stage(stage)
        _check(entry["state"] == "running" and entry["attempts"][-1]["id"] == attempt_id,
               "Stale attempt or stage is not running")
        return entry["attempts"][-1]

    def _fingerprint(self, path: str | Path) -> dict:
        from .align_fingerprint import sha256_file
        resolved = self.resolve_path(path)
        before = resolved.stat()
        _check(stat.S_ISREG(before.st_mode), "Output must be a regular file")
        digest = sha256_file(str(resolved))
        after = resolved.stat()
        _check((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
               (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
               "Output changed during fingerprinting")
        _hash(digest, "output fingerprint")
        return {"path": resolved.relative_to(self.root.resolve()).as_posix(),
                "sha256": digest, "bytes": after.st_size, "mtime_ns": after.st_mtime_ns}

    def record_output(self, stage: str, path: str | Path, *, attempt_id: str) -> dict:
        self._active(stage, attempt_id)
        output = self._fingerprint(path)
        resolved = self.resolve_path(output["path"])
        _check(not any(self.resolve_path(item["path"]) == resolved for item in self._data["outputs"]),
               "Output path already recorded; use a new deliverable path for each attempt")
        if self._path:
            _check(resolved not in (self._path, self.backup_path(self._path)),
                   "Project metadata cannot be a stage output")
        output.update(stage=stage, attempt_id=attempt_id, recorded_at=_now(), valid=True)
        self._data["outputs"].append(output)
        self._touch()
        return copy.deepcopy(output)

    def _finish(self, stage: str, attempt_id: str, state: str, message: str) -> None:
        _check(isinstance(message, str), "Stage message must be a string")
        attempt = self._active(stage, attempt_id)
        attempt.update(state=state, ended_at=_now(), message=message)
        self._stage(stage).update(state=state, reason=message)
        if state != "succeeded":
            for output in self._data["outputs"]:
                if output["attempt_id"] == attempt_id:
                    output["valid"] = False
        self._touch()

    def complete_stage(self, stage: str, *, attempt_id: str) -> None:
        """Record controller success; does not infer science success from exit codes."""
        self._active(stage, attempt_id)
        _check(all(result["status"] == "ok" for result in self.verify_outputs(stage)
                   if result["attempt_id"] == attempt_id),
               "Current attempt outputs are missing, changed, or unavailable")
        self._finish(stage, attempt_id, "succeeded", "")

    def fail_stage(self, stage: str, message: str, *, attempt_id: str) -> None:
        _text(message, "failure message")
        self._finish(stage, attempt_id, "failed", message)

    def skip_stage(self, stage: str, reason: str) -> None:
        self._idle()
        self._predecessors(stage)
        _check(stage != "preprocess", "Preprocess review is mandatory and cannot be skipped")
        _text(reason, "skip reason")
        entry = self._stage(stage)
        _check(entry["state"] in ("pending", "invalidated"), "Restart before skipping")
        entry.update(state="skipped", reason=reason)
        self._touch()

    def restart_stage(self, stage: str, reason: str = "Restart requested") -> None:
        self._stage(stage)
        self._idle()
        _text(reason, "restart reason")
        self._invalidate_from(stage, reason)
        self._touch()

    def recover_interrupted(self, reason: str = "Explicit recovery after interrupted run") -> list[str]:
        """Caller confirms no worker is active; no PID guessing or process control."""
        _text(reason, "recovery reason")
        recovered = []
        for name in STAGES:
            stage = self._stage(name)
            if stage["state"] == "running":
                self._finish(name, stage["attempts"][-1]["id"], "interrupted", reason)
                index = STAGES.index(name) + 1
                if index < len(STAGES):
                    self._invalidate_from(STAGES[index], reason)
                recovered.append(name)
        return recovered

    def verify_outputs(self, stage: str | None = None) -> list[dict]:
        """Read-only full content check, including historical/invalidated outputs."""
        if stage is not None:
            self._stage(stage)
        results = []
        for output in self._data["outputs"]:
            if stage is not None and output["stage"] != stage:
                continue
            result = {key: output[key] for key in ("path", "stage", "attempt_id", "valid")}
            try:
                current = self._fingerprint(output["path"])
                result["status"] = ("ok" if all(current[k] == output[k] for k in ("sha256", "bytes"))
                                    else "changed")
            except FileNotFoundError:
                result["status"] = "missing"
            except (OSError, ProjectError) as exc:
                result.update(status="unavailable", error=str(exc))
            results.append(result)
        return results

    def to_charter(self):
        """Unsigned data adapter using the existing run-charter parser."""
        from .run_charter import parse_charter
        self._validate()
        settings = self._data["settings"]
        return parse_charter({"schema": 1, "campaign": self._data["expedition"],
                              "dive": self._data["dive"],
                              "locations": {"results_root": str(self.resolve_path("proc")),
                                            "originals": list(self._data["sources"]), "nav": []},
                              "science": copy.deepcopy(settings.get("science", {}).get("values", {})),
                              "pipeline": copy.deepcopy(settings.get("pipeline", {}).get("values", {})),
                              "signed_off": {}})

    def to_session(self, stages: list[str] | None = None):
        """Adapt to run_plan.Session without defaults, scans, commands or launching."""
        from .run_plan import ALL_STAGES, session_from_charter
        charter = self.to_charter()
        enabled = list(stages if stages is not None else charter.raw["pipeline"].get("stages", []))
        _check(all(isinstance(s, str) and s in ALL_STAGES for s in enabled),
               "Only existing run_plan stages can be planned")
        # Empty means empty, not session_from_charter's fallback stage selection.
        charter.raw["pipeline"]["stages"] = enabled
        session = session_from_charter(charter, stages=enabled)
        session.continue_automatically = False
        return session
