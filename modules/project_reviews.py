"""Durable content-bound reviews, separate from the small project document.

Review files never execute code. Every approval binds the exact assessment and
selection; changing inputs retires downstream approvals rather than reusing them.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from .source_inventory import SourceInventory, SourceItem, approval_token


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                    separators=(",", ":")).encode()).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".partial")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        from module_base.atomic_io import replace_file
        replace_file(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def claim_root(project, *, adopt_existing=False) -> None:
    """One project UUID owns a processing namespace, even with two filenames.

    Adoption is explicit because an unmarked raw/proc tree can contain valuable
    work. This never clears existing files or changes the UUID of a marked root.
    """
    root = project.root
    root.mkdir(parents=True, exist_ok=True)
    marker = root / ".rovscan-owner.json"
    if marker.is_symlink():
        raise ValueError("Project ownership marker cannot be redirected")
    if marker.exists():
        owner = json.loads(marker.read_text(encoding="utf-8"))
        if type(owner.get("schema")) is not int or owner["schema"] != 1:
            raise ValueError("Unsupported project ownership marker schema")
        if owner.get("project_id") != project.project_id:
            raise ValueError("This project folder belongs to a different project")
        return
    populated = any((root / name).exists() and any((root / name).iterdir())
                    for name in ("raw", "proc", "metadata", "logs"))
    if populated and not adopt_existing:
        raise ValueError("Existing workspace requires explicit adoption before processing")
    # Exclusive creation closes the two-window first-use race.
    with marker.open("x", encoding="utf-8") as stream:
        json.dump({"schema": 1, "project_id": project.project_id,
                   "adopted_existing": populated,
                   "created_at": datetime.now(timezone.utc).isoformat()}, stream)
        stream.flush()
        os.fsync(stream.fileno())


class ReviewStore:
    """Persist assessments and approvals under the owning project's metadata."""

    NAMES = ("inventory", "navigation", "georeference", "quality", "spatial", "selection", "workflow", "occlusion_review")

    def __init__(self, project):
        self.project = project
        self.root = project.resolve_path("metadata/reviews")

    def path(self, name):
        if name not in self.NAMES:
            raise ValueError("Unknown review kind")
        path = self.root / (name + ".json")
        if not path.resolve().is_relative_to(self.project.root):
            raise ValueError("Review path escapes the project")
        return path

    def read(self, name, *, required=True):
        path = self.path(name)
        if not path.exists() and not required:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("project_id") != self.project.project_id:
            raise ValueError("Review belongs to a different project")
        return value

    def put(self, name, payload, *, invalidate=()):
        value = {"schema": 1, "project_id": self.project.project_id,
                 "payload": payload, "assessment_hash": digest(payload), "approval": None}
        claim_root(self.project)
        # Invalidate first: interruption must fail closed, never leave an old
        # approval attached to newly written evidence.
        if name in ("inventory", "navigation", "georeference", "quality", "spatial", "selection", "workflow"):
            invalidate = tuple(dict.fromkeys((*invalidate, "occlusion_review")))
        for downstream in invalidate:
            old = self.read(downstream, required=False)
            if old:
                old["approval"] = None
                old["invalidated_by"] = name
                write_json(self.path(downstream), old)
        write_json(self.path(name), value)
        return value

    def approve(self, name, assessment_hash, by):
        claim_root(self.project)
        if not isinstance(by, str) or not by.strip():
            raise ValueError("Reviewer identity is required")
        value = self.read(name)
        if (value["assessment_hash"] != assessment_hash
                or digest(value["payload"]) != assessment_hash
                or value.get("invalidated_by")):
            raise ValueError("Assessment changed; review the current result")
        if name == "occlusion_review":
            self._validate_occlusion_decision(value["payload"])
        value["approval"] = {"assessment_hash": assessment_hash, "by": by,
                             "at": datetime.now(timezone.utc).isoformat()}
        write_json(self.path(name), value)
        return value

    def require_approved(self, name):
        value = self.read(name)
        approval = value.get("approval") or {}
        if (value.get("invalidated_by") or not approval.get("by")
                or approval.get("assessment_hash") != digest(value["payload"])
                or value["assessment_hash"] != digest(value["payload"])):
            raise ValueError(f"Current {name} review must be confirmed")
        return value

    @staticmethod
    def _validate_occlusion_decision(payload):
        fingerprint = payload.get("batch_fingerprint")
        if (not isinstance(fingerprint, str) or len(fingerprint) != 64
                or any(c not in "0123456789abcdef" for c in fingerprint)):
            raise ValueError("Occlusion review requires the current batch content fingerprint")
        if payload.get("decision") not in ("applied", "skipped"):
            raise ValueError("Review and apply generated masks, or explicitly skip optional ROV masking")
        if payload["decision"] == "skipped" and (not isinstance(payload.get("reason"), str) or not payload["reason"].strip()):
            raise ValueError("Skipping optional ROV masking requires a reason")

    def require_occlusion_review(self, batch_fingerprint):
        """Alignment gate; the caller fingerprints current batch/image content.

        Generation alone never approves masks. The controller validates generated
        mask artifacts before recording an applied decision; this store binds that
        decision (or explicit Skip) to the exact batch being aligned.
        """
        if self.read("occlusion_review", required=False) is None:
            raise ValueError("Generate and apply, or explicitly skip post-batch ROV masking before alignment")
        value = self.require_approved("occlusion_review")
        self._validate_occlusion_decision(value["payload"])
        if value["payload"]["batch_fingerprint"] != batch_fingerprint:
            raise ValueError("Batch/image content changed; review optional ROV masking again")
        return value

    def save_inventory(self, inventory, *, decisions=None, source_mask_policy=None):
        """Retire source masks by explicit policy, preserving it across rescans.

        No source files are changed. Legacy first saves without a policy preserve
        their inclusion values; native consumers must require ignore_existing.
        """
        previous = self.read("inventory", required=False)
        if source_mask_policy is None and previous:
            source_mask_policy = previous["payload"].get("source_mask_policy")
        if source_mask_policy not in (None, "ignore_existing"):
            raise ValueError("Unsupported source mask policy")
        decisions = dict(decisions if decisions is not None else
                         (previous or {}).get("payload", {}).get("decisions", {}))
        if source_mask_policy == "ignore_existing":
            for item in inventory:
                if item.kind == "mask":
                    item.included = False
                    decisions[item.path] = {"included": False,
                        "reason": "Source mask retired by ignore_existing policy; optional masks are reviewed after batching"}
        return self.put("inventory", {"source_root": inventory.source_root,
            "source_fingerprint": inventory.source_fingerprint,
            "dive_window": inventory.dive_window, "hashing_complete": inventory.hashing_complete,
            "verification_complete": inventory.verification_complete,
            "items": [asdict(im) for im in inventory],
            "input_inventory_hash": approval_token(inventory), "decisions": decisions,
            "source_mask_policy": source_mask_policy},
            invalidate=("quality", "spatial", "selection"))

    def inventory(self, *, approved=False):
        value = self.require_approved("inventory") if approved else self.read("inventory")
        data = value["payload"]
        policy = data.get("source_mask_policy")
        if policy not in (None, "ignore_existing"):
            raise ValueError("Unsupported source mask policy")
        if policy == "ignore_existing" and any(
                item.get("kind") == "mask" and item.get("included") is not False for item in data["items"]):
            raise ValueError("Retired source masks cannot be included")
        inventory = SourceInventory([SourceItem(**item) for item in data["items"]],
            source_root=data["source_root"], fingerprint=data["source_fingerprint"],
            dive_window=data["dive_window"], hashing_complete=data.get("hashing_complete"),
            verification_complete=data.get("verification_complete"))
        if approval_token(inventory) != data["input_inventory_hash"]:
            raise ValueError("Stored inventory content does not match its fingerprint")
        return inventory

    def selection(self):
        """Final mask-aware include set; both review gates must still agree."""
        inventory = self.inventory(approved=True)
        quality = self.require_approved("quality")["payload"]
        spatial = self.require_approved("spatial")["payload"]
        token = approval_token(inventory)
        if quality["input_inventory_hash"] != token or spatial["input_inventory_hash"] != token:
            raise ValueError("Image selection was reviewed against a different inventory")
        if spatial["quality_selection_hash"] != digest(quality):
            raise ValueError("Density review predates the current image culling")
        excluded = set(quality["excluded_paths"]) | set(spatial["excluded_paths"])
        known = {im.path for im in inventory if im.kind == "image"}
        if not excluded <= known:
            raise ValueError("Culling contains an image outside the inventory")
        for item in inventory:
            if item.kind == "image" and item.path in excluded:
                item.included = False
        by_path = {im.path: im for im in inventory}
        for item in inventory:
            if item.duplicate_of and not by_path[item.duplicate_of].included:
                item.included = False
        for item in inventory:
            if item.kind == "mask":
                item.included = item.included and bool(item.mask_for) and by_path[item.mask_for].included
        if not any(im.kind == "image" and im.included and not im.duplicate_of for im in inventory):
            raise ValueError("The approved selection contains no usable images")
        return inventory
