"""Native project orchestration over the existing planner and execution lane.

UI callbacks receive data only. Scientific settings and review decisions are
persisted before work starts; previews never implicitly authorize processing.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, fields
from datetime import datetime, timezone
from functools import wraps
import copy
import json
import logging
from pathlib import Path
import shutil
import sys
import threading
import time
from uuid import uuid4

from .project_reviews import ReviewStore, claim_root, digest, write_json
from .project_runtime import ExecutionControl, OwnershipUnconfirmed
from .source_inventory import (approval_token, assert_source_unchanged,
    file_hash, reconcile_image_identities, stage_inventory, summarize_inventory)

REPO = Path(__file__).resolve().parent.parent
GIB = 1024 ** 3
GEO_SETTINGS_BLOCKS = ("navigation", "cameras", "georeference")


def track_segments(frame, *, max_gap_seconds=2.0):
    """Break track polylines at missing navigation samples, retaining float64 XY."""
    from math import isfinite
    if not isfinite(max_gap_seconds) or max_gap_seconds <= 0:
        raise ValueError("Track gap threshold must be positive and finite")
    segments, current, previous = [], [], None
    for stamp, x, y in frame[["Timestamp", "kalman_x", "kalman_y"]].itertuples(index=False, name=None):
        if not isfinite(float(x)) or not isfinite(float(y)):
            raise ValueError("Track coordinates must be finite")
        if previous is not None:
            elapsed = (stamp - previous).total_seconds()
            if elapsed <= 0:
                raise ValueError("Track timestamps must be strictly increasing")
            if elapsed > max_gap_seconds:
                segments.append(current)
                current = []
        current.append([float(x), float(y)])
        previous = stamp
    if current:
        segments.append(current)
    return segments


def _project_mutation(method):
    """Serialize short review/settings mutations with long project operations."""
    @wraps(method)
    def guarded(self, project, *args, **kwargs):
        with self._lock:
            self._idle()
            lease = self._acquire_project(project)
            self._project = project
            self._project_lease = lease
            self._mutation_events = []
            try:
                result = method(self, project, *args, **kwargs)
            except BaseException:
                self._mutation_events = None
                self._release_project_lease(project, lease)
                raise
            else:
                pending = self._mutation_events
                self._mutation_events = None
                self._release_project_lease(project, lease)
                self._emit(None, _batch_events=pending)
                return result
    return guarded


class ProjectController:
    def __init__(self):
        self._listeners = []
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rovscan")
        self._lock = threading.RLock()
        self._future = None
        self._operation_finished = True
        self._control = ExecutionControl()
        self._project = None
        self._sequence = 0
        self._ownership_unconfirmed = False
        self._resource_alerted = False
        self._last_progress = 0.0
        self._project_lease = None
        self._mutation_events = None
        self._event_queue = []
        self._dispatching_events = False

    def subscribe(self, callback):
        with self._lock:
            self._listeners.append(callback)
        def unsubscribe():
            with self._lock:
                if callback in self._listeners:
                    self._listeners.remove(callback)
        return unsubscribe

    def _emit(self, kind, *, _batch_events=None, **data):
        if kind == "progress":
            now = time.monotonic()
            if data.get("current") != data.get("total") and now - self._last_progress < 0.2:
                return
            self._last_progress = now
        with self._lock:
            pending = _batch_events if _batch_events is not None else [(kind, data, self._project)]
            if self._mutation_events is not None:
                self._mutation_events.extend(pending)
                return
            self._event_queue.extend(pending)
            if self._dispatching_events:
                return
            self._dispatching_events = True
            try:
                while self._event_queue:
                    event_kind, payload, project = self._event_queue.pop(0)
                    self._sequence += 1
                    event = {"kind": event_kind, "sequence": self._sequence,
                             "at": datetime.now(timezone.utc).isoformat(), **payload}
                    if project is not None:
                        event["project_id"] = project.project_id
                    listeners = list(self._listeners)
                    # Bind both deferred logs and GUI events to their originating
                    # project, even if a prior callback opened another project.
                    if project is not None:
                        path = project.resolve_path("logs/controller.jsonl")
                        try:
                            path.parent.mkdir(parents=True, exist_ok=True)
                            recorded = dict(event)
                            for key in ("items", "candidates", "points", "track", "track_segments",
                                        "groups", "copies", "mappings"):
                                if key in recorded:
                                    recorded[key + "_count"] = len(recorded.pop(key))
                            if event_kind in ("inventory", "image_quality", "spatial_review", "occlusion_masks"):
                                recorded["review_artifact"] = {"inventory": "inventory", "image_quality": "quality",
                                    "spatial_review": "spatial", "occlusion_masks": "occlusion_review"}[event_kind]
                            with path.open("a", encoding="utf-8") as stream:
                                stream.write(json.dumps(recorded, allow_nan=False) + "\n")
                        except OSError:
                            event["logging_error"] = "Cannot append the project event log"
                    for listener in listeners:
                        try:
                            listener(event)
                        except Exception:
                            logging.getLogger(__name__).exception("Project event listener failed for %s", event_kind)
            finally:
                self._dispatching_events = False

    def _release_project_lease(self, project, lease):
        """A failed close retains ownership; callers must not announce release."""
        try:
            lease.close()
        except BaseException as exc:
            self._project = project
            self._project_lease = lease
            self._ownership_unconfirmed = True
            self._operation_finished = False
            message = f"Workspace lease release could not be confirmed: {exc}"
            self._emit("state", state="ownership_unconfirmed", message=message, ownership_released=False)
            raise OwnershipUnconfirmed(message) from exc
        else:
            if self._project_lease is lease:
                self._project_lease = None

    def _idle(self):
        if self._ownership_unconfirmed:
            raise OwnershipUnconfirmed("Previous runtime ownership must be reconciled before another operation")
        if not self._operation_finished:
            raise ValueError("A project operation is still running")

    def _acquire_project(self, project, *, recover_backup_for_save=False):
        from .realityscan_interface.realityscan_cli import _OSLock
        claim_root(project)
        try:
            lease = _OSLock(str(project.root / ".rovscan-operation.lock"))
        except OSError as exc:
            raise ValueError("Another application window is operating this project") from exc
        try:
            data = project.to_dict()
            if project.path and project.path.exists():
                from .project_workspace import ProjectDocument
                disk = ProjectDocument.load(project.path,
                    recover_backup=recover_backup_for_save and project.recovered_from_backup).to_dict()
                if disk["id"] != data["id"]:
                    raise ValueError("Saved project identity changed; reopen before continuing")
                if any(s["state"] == "running" for s in disk["stages"].values()):
                    raise OwnershipUnconfirmed("A persisted project attempt is still running; reconcile before changing the project")
            if any(s["state"] == "running" for s in data["stages"].values()):
                raise OwnershipUnconfirmed("Project has a running attempt; reconcile before changing the project")
            return lease
        except BaseException:
            self._release_project_lease(project, lease)
            raise

    def _submit(self, project, stage, operation):
        with self._lock:
            self._idle()
            lease = self._acquire_project(project)
            try:
                project.create_layout()
            except BaseException:
                self._release_project_lease(project, lease)
                raise
            self._project_lease = lease
            self._project = project
            self._control = ExecutionControl()
            self._resource_alerted = False
            self._operation_finished = False
            self._emit("state", stage=stage, state="running", ownership_released=False)
            def work():
                terminal = dict(state="review_ready", ownership_released=True)
                try:
                    operation()
                except OwnershipUnconfirmed as exc:
                    self._ownership_unconfirmed = True
                    self._emit("error", message=str(exc))
                    terminal = dict(state="ownership_unconfirmed", message=str(exc), ownership_released=False)
                except BaseException as exc:
                    self._emit("error", message=f"{type(exc).__name__}: {exc}")
                    terminal = dict(state="failed", message=str(exc), ownership_released=True)
                finally:
                    with self._lock:
                        if not self._ownership_unconfirmed:
                            try:
                                self._release_project_lease(project, lease)
                            except OwnershipUnconfirmed:
                                terminal = None  # The close failure already announced retained ownership.
                            else:
                                self._operation_finished = True
                        # All operation writes and lease release precede notification.
                        # A direct listener may now start another queued operation.
                        if terminal is not None:
                            self._emit("state", stage=stage, **terminal)
            try:
                self._future = self._pool.submit(work)
            except BaseException as exc:
                self._release_project_lease(project, lease)
                self._operation_finished = True
                self._emit("state", stage=stage, state="failed", message=str(exc), ownership_released=True)
                raise

    def stop(self, mode="after_step"):
        self._control.request_cancel(mode)
        self._emit("state", state="cancel_requested", ownership_released=False,
                   message="Waiting for the owned operation to stop safely")

    def _cancelled(self):
        return self._control.cancellation_requested and self._control.mode == "abort_current"

    def _observe(self, event):
        """Preserve raw runtime evidence and translate it for the native UI."""
        self._emit(**event)
        if event.get("kind") != "runtime":
            return
        runtime = event["event"]
        kind, data = runtime.get("kind"), runtime.get("data", {})
        if kind == "resources":
            free = [data[key] for key in ("disk_free_gb", "cache_free_gb") if data.get(key) is not None]
            reserve = float(self._values(self._project, "operating")["reserve_gib"])
            self._emit("resources", free_bytes=int(min(free) * GIB) if free else None,
                       reserve_bytes=int(reserve * GIB), memory_bytes=None)
            if free and min(free) < reserve and not self._resource_alerted:
                self._resource_alerted = True
                self._control.request_cancel("after_step")
                self._emit("error", message="FREE-SPACE RESERVE REACHED. No further stage will start. Current operation still owns its instance; choose Abort current to stop it, or free space outside protected data.")
        elif kind in ("progress_stalled", "stalled"):
            self._emit("error", message="RealityScan progress has stalled. Inspect the current operation and logs; Abort current remains available. Elapsed time alone is not completion.")
        elif kind == "progress":
            self._emit("progress", stage="RealityScan", current=0, total=0,
                       message=data.get("raw", "Waiting for progress evidence"))

    @staticmethod
    def _values(project, block):
        return project.to_dict()["settings"].get(block, {}).get("values", {})

    @staticmethod
    def _source(project):
        sources = project.to_dict()["sources"]
        if len(sources) != 1:
            raise ValueError("Select one dive delivery root containing imagery and cruise_data")
        return Path(sources[0])

    def adopt_workspace(self, project):
        self._idle()
        claim_root(project, adopt_existing=True)

    def save_project(self, project, path=None):
        # Only explicit Save may repair a primary already opened from backup.
        # Execution paths still refuse unreadable persisted ownership state.
        with self._lock:
            self._idle()
            lease = self._acquire_project(project, recover_backup_for_save=True)
            try:
                self._project = project
                self._project_lease = lease
                return project.save(path)  # Core compare-and-swap remains mandatory.
            finally:
                self._release_project_lease(project, lease)

    def ensure_cache(self, project):
        """Create only the explicitly approved cache inside this project."""
        if not project.settings_approved(["operating"]):
            raise ValueError("Approve the operating settings before creating the cache")
        claim_root(project)
        cache = Path(self._values(project, "operating")["cache_dir"]).resolve()
        if not cache.is_relative_to(project.resolve_path("proc/tmp")):
            raise ValueError("Cache must remain inside this project's proc/tmp")
        cache.mkdir(parents=True, exist_ok=True)
        return cache

    def load_project_state(self, project):
        """Read persisted review state without changing files or starting work."""
        store = ReviewStore(project)
        events = []
        inventory = store.read("inventory", required=False)
        if inventory:
            items = store.inventory()
            summary = summarize_inventory(items)
            events.append({"kind": "inventory", "items": [asdict(item) for item in items],
                "camera_summary": [{"camera_type": key, **row} for key, row in summary["cameras"].items()],
                "camera_family_summary": [{"family": key, **row} for key, row in summary.get("families", {}).items()],
                "input_inventory_hash": approval_token(items), "inventory_confirmed": bool(inventory["approval"])})
        navigation = store.read("navigation", required=False)
        current_navigation, navigation_error = None, None
        if navigation:
            try:
                current_navigation, _ = self._navigation(project)
                events.append({"kind": "navigation", "items": [current_navigation]})
            except (OSError, ValueError, KeyError) as exc:
                navigation_error = str(exc)
                events.append({"kind": "state", "stage": "navigation", "state": "review_invalid",
                    "message": navigation_error, "ownership_released": True})
        quality = store.read("quality", required=False)
        if quality:
            payload = quality["payload"]
            events.append({"kind": "image_quality", "assessment_hash": quality["assessment_hash"],
                "tolerances": payload["tolerances"], "candidates": [
                    {"path": r["image_path"], "excluded": r["image_path"] in payload["excluded_paths"], **r}
                    for r in payload["results"] if r["decision"] != "keep"], "summary": {"images": len(payload["results"])}})
            if quality["approval"] and not quality.get("invalidated_by"):
                store.require_approved("quality")
                events.append({"kind": "state", "stage": "preprocess", "state": "quality_confirmed", "ownership_released": True})
        spatial = store.read("spatial", required=False)
        if spatial:
            events.append({"kind": "spatial_review", **spatial["payload"]["assessment"],
                "spatial_excluded_paths": spatial["payload"]["excluded_paths"], "assessment_hash": spatial["assessment_hash"]})
            if spatial["approval"] and not spatial.get("invalidated_by"):
                try:
                    store.selection()
                    if current_navigation is None:
                        raise ValueError(navigation_error or "Navigation validation is missing; rebuild the density review")
                    if spatial["payload"].get("navigation_sha256") != current_navigation["sha256"]:
                        raise ValueError("Navigation changed since the density review; rebuild the plot")
                except (OSError, ValueError, KeyError) as exc:
                    events.append({"kind": "state", "stage": "preprocess", "state": "review_invalid",
                        "message": str(exc), "ownership_released": True})
                else:
                    events.append({"kind": "state", "stage": "preprocess", "state": "selection_confirmed", "ownership_released": True})
        if project.to_dict()["stages"]["batch"]["state"] == "succeeded":
            # Restore the saved decision without hashing an entire dive on the
            # GUI thread. Execution independently validates current batch bytes.
            events.append(self._occlusion_event_data(project))
        return events

    def recover_project(self, project):
        """Recover only attempts with attributable terminal execution evidence.

        Unknown process/instance state stays blocked. An operator assertion is
        not a substitute for the original executor's release evidence.
        """
        from .project_runtime import inspect_recovery, require_runtime_release
        from .realityscan_interface.realityscan_cli import _OSLock
        if self._future and not self._future.done():
            raise OwnershipUnconfirmed("The project operation is still being monitored")
        if self._project_lease is not None and self._project.project_id != project.project_id:
            raise OwnershipUnconfirmed("A different project still owns the retained operation")
        claim_root(project)
        acquired = self._project_lease is None
        try:
            lease = self._project_lease or _OSLock(str(project.root / ".rovscan-operation.lock"))
        except OSError as exc:
            raise OwnershipUnconfirmed("Another window still owns this project") from exc
        try:
            running = {stage: entry["attempts"][-1]["id"] for stage, entry in project.to_dict()["stages"].items()
                       if entry["state"] == "running"}
            if self._ownership_unconfirmed and not running:
                raise OwnershipUnconfirmed("Retained operation has no attributable stage record; do not release its ownership")
            for stage, attempt in running.items():
                plans = []
                for path in project.resolve_path("metadata/plans").glob("*.json"):
                    plan = json.loads(path.read_text(encoding="utf-8"))
                    if not isinstance(plan, dict):
                        raise ValueError("Launch record must be an object")
                    if plan.get("project_id") == project.project_id and plan.get("project_attempt_id") == attempt:
                        plans.append(plan)
                if not plans:
                    raise OwnershipUnconfirmed(f"{stage}: no attributable launch record. Keep the project closed to processing until the original worker is reconciled")
                for plan in plans:
                    commands = plan.get("commands")
                    if not isinstance(commands, list) or not commands or any(not isinstance(c, dict) for c in commands):
                        raise ValueError("Launch record requires nonempty command objects")
                    if stage in ("align", "merge", "model", "export") and not all(c.get("needs_realityscan") is True for c in commands):
                        raise ValueError("RealityScan stage cannot downgrade its application ownership evidence")
                    state_path = project.resolve_path(plan["run_state"])
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    if not isinstance(state, dict) or state.get("label") != plan["execution_label"]:
                        raise ValueError("Executor state is not bound to this launch")
                    if state.get("status") in ("done", "failed", "cancelled"):
                        if type(state.get("returncode")) is not int or state.get("ownership_released") is not True:
                            raise ValueError("Executor has not confirmed child shutdown and ownership release")
                        for command in commands:
                            require_runtime_release(command)
                    else:
                        # After an app crash, the original process identity and
                        # fresh runtime events can prove release without a UI assertion.
                        active = [c for c in commands if c.get("stage") == state.get("stage")]
                        if len(active) != 1:
                            raise ValueError("Interrupted command cannot be identified uniquely")
                        proof = inspect_recovery(active[0], state, expected_project_id=project.project_id,
                                                 expected_attempt_id=attempt)
                        if not proof["can_recover"]:
                            raise OwnershipUnconfirmed(f"{stage}: original worker release remains unconfirmed: {proof}")
            recovered = project.recover_interrupted("Executor shutdown/release evidence verified by project controller")
            project.save()
            self._ownership_unconfirmed = False
            return {"ownership_released": True, "recovered_stages": recovered,
                    "message": "Interrupted attempts invalidated; restart from the selected step"}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise OwnershipUnconfirmed(f"Recovery evidence is unavailable or invalid: {exc}") from exc
        finally:
            if acquired or not self._ownership_unconfirmed:
                self._release_project_lease(project, lease)
                if not self._ownership_unconfirmed:
                    self._operation_finished = True

    def _record_execution_plan(self, project, stage, plan, agent_workspace):
        attempt = project.to_dict()["stages"][stage]["attempts"][-1]["id"]
        label = project.project_id + "/" + attempt
        plan.update(project_id=project.project_id, project_attempt_id=attempt, execution_label=label,
                    run_state=(Path(agent_workspace) / "RUN_STATE.json").relative_to(project.root).as_posix())
        for command in plan["commands"]:
            command.update(project_id=project.project_id, project_attempt_id=attempt)
        write_json(project.resolve_path("metadata/plans/" + uuid4().hex + ".json"), plan)
        return label

    def settings_schema(self, project):
        from . import camera_registry
        from .rs_installation import DEFAULT_INSTALL_DIR
        data = project.to_dict()
        result = []
        def add(block, key, label, default, help="", **extra):
            kind = "bool" if type(default) is bool else "int" if type(default) is int else "float" if type(default) is float else "str"
            result.append({"block": block, "key": key, "label": label, "type": kind,
                           "default": default, "help": help, **extra})
        add("operating", "install_dir", "RealityScan 2.2 installation", str(DEFAULT_INSTALL_DIR), type="path")
        add("operating", "instance", "Dedicated RealityScan instance", f"ROV_{data['expedition']}_{data['dive']}")
        add("operating", "cache_dir", "Project cache", str(project.resolve_path("proc/tmp/cache")), type="path")
        add("operating", "reserve_gib", "Free-space reserve (GiB)", 50.0, min=1)
        add("navigation", "max_match_seconds", "Maximum image/navigation difference (seconds)", 2.0, min=0)
        add("navigation", "clock_offset_seconds", "Image UTC clock correction (seconds)", 0.0)
        for family, mount in camera_registry.baked_mount_defaults().items():
            if mount is None:
                continue
            names = {"fwd": "Forward offset (m)", "lat": "Right offset (m)",
                     "down": "Downward offset (m)", "pitch": "Starting downward tilt (degrees)",
                     "p_acc": "Pitch accuracy (degrees)"}
            for key, value in mount.items():
                add("cameras", family + "." + key, family.replace("_", " ") + ": " + names.get(key, key), value,
                    "Applied when vehicle navigation is converted to camera priors")
        add("cameras", "orientation_weight", "Orientation prior weight (locked)", 2.0, min=2, max=2)
        defaults = camera_registry.baked_prior_defaults()
        for group in ("position_accuracy_m", "orientation_accuracy_deg"):
            for key, value in defaults[group].items():
                if not key.startswith("_"):
                    label = ({"x": "East position accuracy (m)", "y": "North position accuracy (m)",
                              "alt": "Depth / vertical accuracy (m)"}.get(key, key)
                             if group == "position_accuracy_m" else key.title() + " accuracy (degrees)")
                    add("cameras", "defaults." + group + "." + key, label, value, min=0.001)
        from .run_plan import _module_registry, _FORCED_ANSWERS
        derived = {"g_input", "g_flight_log", "g_type", "b_input", "b_flight_log_path",
                   "r_input", "r_flight_log", "r_project_label", "output_dir", "continue_automatically"}
        for stage in ("georeference", "batch", "align"):
            for param in _module_registry()[stage].get_parameters().values():
                if param.cli_long in derived or param.cli_long in _FORCED_ANSWERS:
                    continue
                if stage == "georeference" and param.cli_long in {"g_pos_accuracy", "g_alt_accuracy", "g_orientation_accuracy"}:
                    continue  # Authoritative per-camera contract supplies these.
                if stage == "batch" and param.cli_long == "b_zone_layout":
                    add(stage, param.cli_long, param.name, "copy",
                        "The native project workflow uses per-zone copies for reviewed ROV masks",
                        type="choice", choices=["copy"])
                    continue
                add(stage, param.cli_long, param.name,
                    "" if param.default_value is None else param.default_value,
                    param.description or "", required=param.default_value is None)
        metadata = REPO / "modules/realityscan_interface/RS_CLI/Metadata"
        add("science", "align_settings_xml", "Alignment settings XML", str(metadata / "AlignmentParams.xml"), type="path", path_kind="file")
        add("science", "identity_capture", "Per-component identity capture", "xmp", type="choice", choices=["xmp", "csv"])
        add("science", "min_component_size", "Minimum component images", 50, min=1)
        add("merge", "horizontal_margin_m", "Orphan search: horizontal uncertainty (m)", 7.1,
            "Proposed margin around either alignment or the corridor between them; confirm before merging", min=0)
        add("merge", "vertical_margin_m", "Orphan search: depth uncertainty (m)", 1.0,
            "Reject images farther above or below the local alignment/corridor than this margin", min=0)
        add("merge", "footprint_link_m", "Maximum spacing within an alignment footprint (m)", 20.0,
            "Do not fill large unsurveyed gaps inside an alignment when selecting orphan images", min=0.001)
        add("merge", "max_corridor_m", "Maximum bridge between the two alignments (m)", 50.0,
            "Only the nearest connecting corridor is searched; distant regions remain excluded", min=0)
        add("merge", "max_offered", "Maximum orphan images offered per merge", 2000,
            "An over-limit attempt stops for review; images are never silently truncated", min=1)
        add("merge", "vertical_datum", "Declared height/depth reference", "",
            "Required: identify the reference used by the selected navigation heights", required=True)
        add("merge", "component_features", "Feature source for imported alignments", 0,
            "New orphan images always use all image features", type="choice",
            choices=[{"label": "Merge using overlapping images", "value": 0},
                     {"label": "Use component features", "value": 1},
                     {"label": "Use all image features", "value": 2}])
        for key, label in (("expected_hours", "Expected duration (hours)"), ("memory_peak_gb", "Expected peak memory (GiB)"),
                           ("disk_delta_gb", "Estimated additional output size (GiB)"),
                           ("cache_delta_gb", "Estimated additional cache size (GiB)")):
            add("budget", key, label, 0.0, "A declared processing budget; not an operation timeout", min=0)
        add("budget", "abort_criteria", "Pause/alert criteria", "Pause and alert below free-space reserve or on sustained stall")
        return result

    @_project_mutation
    def apply_settings(self, project, block, values):
        self._idle()
        if block == "batch" and values.get("b_zone_layout", "copy") != "copy":
            raise ValueError("The native project workflow requires copy batch layout for post-batch mask review")
        if block == "cameras" and values.get("orientation_weight") != 2:
            raise ValueError("Orientation prior weight is locked at 2")
        if block == "operating":
            cache = Path(values["cache_dir"]).resolve()
            if not cache.is_relative_to(project.resolve_path("proc/tmp")):
                raise ValueError("Cache must stay under this project's proc/tmp")
            if float(values["reserve_gib"]) < 1:
                raise ValueError("A positive storage reserve is required")
        previous = project.to_dict()["settings"].get(block)
        if previous is not None and digest(previous["values"]) == digest(values):
            return
        from .project_workspace import settings_stage
        affected = settings_stage(block)
        project.set_settings(block, values)
        store = ReviewStore(project)
        if affected in ("inventory", "navigation", "georeference"):
            reviews = ("georeference", "quality", "spatial", "selection", "workflow", "occlusion_review")
        elif affected == "preprocess":
            reviews = ("quality", "spatial", "selection", "workflow", "occlusion_review")
        elif affected == "batch":
            reviews = ("workflow", "occlusion_review")
        else:
            reviews = ()
        for name in reviews:
            old = store.read(name, required=False)
            if old:
                old["approval"] = None
                old["invalidated_by"] = "settings"
                write_json(store.path(name), old)

    def _inventory_event(self, project):
        store = ReviewStore(project)
        value = store.read("inventory")
        items = store.inventory()
        summary = summarize_inventory(items)
        self._emit("inventory", items=[asdict(item) for item in items],
            camera_summary=[{"camera_type": key, **row} for key, row in summary["cameras"].items()],
            camera_family_summary=[{"family": key, **row} for key, row in summary.get("families", {}).items()],
            input_inventory_hash=approval_token(items), inventory_confirmed=bool(value["approval"]))

    def scan_inventory(self, project):
        def scan():
            from integrations.rovdataconcat.navigation import source_window
            from .inventory_checkpoint import scan_inventory
            data = project.to_dict()
            window = source_window(self._source(project), project.root, data["expedition"], data["dive"])
            # Window discovery is cheap; the navigation stage separately builds
            # its full sensor manifest. A resumed census never restores approval.
            items = scan_inventory(self._source(project),
                project.resolve_path("proc/tmp/inventory_checkpoint"),
                launch=window["launch_utc"], recovery=window["recovery_utc"],
                cancelled=self._cancelled,
                progress=lambda phase, current, total, path: self._emit(
                    "progress", stage="inventory", phase=phase, current=current,
                    total=total, message=f"{phase}: {path}"))
            ReviewStore(project).save_inventory(items, source_mask_policy="ignore_existing")
            write_json(project.resolve_path("metadata/navigation_window.json"), window)
            self._inventory_event(project)
        self._submit(project, "inventory", scan)

    def set_inventory_decision(self, project, path, included, reason):
        return self.set_inventory_decisions(project, [path], included, reason)

    @_project_mutation
    def set_inventory_decisions(self, project, paths, included, reason):
        """Apply one reviewed selection atomically, with one census write."""
        self._idle()
        if type(included) is not bool or not str(reason).strip():
            raise ValueError("An include/exclude decision requires a reason")
        if not isinstance(paths, (list, tuple)) or not paths or any(not isinstance(p, str) for p in paths):
            raise ValueError("Choose one or more inventoried paths")
        selected = set(paths)
        store = ReviewStore(project)
        value = store.read("inventory")
        items = store.inventory()
        matching = [item for item in items if item.path in selected]
        if len(matching) != len(selected) or any(item.kind not in ("image", "mask") for item in matching):
            raise ValueError("Choose an inventoried geometry image or mask")
        for item in matching:
            if item.kind == "mask" and (included or not item.exception):
                raise ValueError("Valid masks follow their matched image; only flagged masks may be explicitly excluded")
            if included and (item.exception or item.window_status != "in_window"):
                raise ValueError("Fix the image/time/camera exception before including this image")
        for item in matching:
            item.included = included
        reconcile_image_identities(items)
        for mask in items:
            if mask.kind == "mask" and mask.mask_for in selected:
                mask.included = (value["payload"].get("source_mask_policy") != "ignore_existing"
                    and included and not bool(mask.exception))
        decisions = value["payload"].get("decisions", {})
        for path in selected:
            decisions[path] = {"included": included, "reason": reason}
        store.save_inventory(items, decisions=decisions)
        self._emit("inventory_decision", paths=sorted(selected), included=included, reason=reason)
        self._inventory_event(project)

    @_project_mutation
    def confirm_inventory(self, project, input_inventory_hash, confirmed_by):
        self._idle()
        store = ReviewStore(project)
        items = store.inventory()
        assert_source_unchanged(items)
        if approval_token(items) != input_inventory_hash:
            raise ValueError("Source inventory changed; rescan before confirmation")
        errors = [item for item in items if item.included and item.exception]
        if errors:
            raise ValueError(f"Resolve or exclude {len(errors)} flagged files before confirmation")
        value = store.read("inventory")
        store.approve("inventory", value["assessment_hash"], confirmed_by)
        self._finish_review_stage(project, "inventory", store.read("inventory"))
        self._inventory_event(project)

    def _finish_review_stage(self, project, stage, evidence):
        if project.to_dict()["stages"][stage]["state"] not in ("pending", "invalidated"):
            project.restart_stage(stage, "Reviewed inputs changed")
        attempt = project.start_stage(stage, required_blocks=[])
        path = project.resolve_path(f"metadata/attempts/{attempt}/review.json")
        write_json(path, evidence)
        project.record_output(stage, path, attempt_id=attempt)
        project.complete_stage(stage, attempt_id=attempt)
        project.save()

    def _navigation(self, project):
        from .navigation_quality import load_navigation
        value = ReviewStore(project).read("navigation")["payload"]
        path = project.resolve_path(value["relative_path"])
        if file_hash(path) != value["sha256"]:
            raise ValueError("Navigation artifact changed since validation")
        data = project.to_dict()
        return value, load_navigation(path, data["expedition"], data["dive"])

    @staticmethod
    def _require_retired_source_masks(store, items):
        """Native processing never adopts masks delivered with source imagery."""
        if any(item.kind == "mask" for item in items):
            if store.read("inventory")["payload"].get("source_mask_policy") != "ignore_existing":
                raise ValueError("Rescan inventory to retire existing source masks before processing; optional ROV masks are reviewed after batching")
            if any(item.kind == "mask" and item.included for item in items):
                raise ValueError("Retired source masks cannot be processed")

    def scan_image_quality(self, project, tolerances=None):
        def scan():
            from .image_quality import ScreeningThresholds, assess_image
            config = ScreeningThresholds(**(tolerances or {}))
            config.validate()
            store = ReviewStore(project)
            if project.to_dict()["stages"]["georeference"]["state"] != "succeeded":
                raise ValueError("Complete navigation matching/georeferencing before image screening")
            items = store.inventory(approved=True)
            self._require_retired_source_masks(store, items)
            assert_source_unchanged(items)
            images = [item for item in items if item.kind == "image" and item.included and not item.duplicate_of]
            masks = {}
            for mask in items:
                if mask.kind == "mask" and mask.included:
                    masks.setdefault(mask.mask_for, []).append(mask)
            results = []
            artifacts = project.resolve_path("proc/tmp/reviews/" + uuid4().hex)
            for index, item in enumerate(images):
                if self._cancelled():
                    raise InterruptedError("Image screening cancelled; previous decisions are retained")
                associated = masks.get(item.path, [])
                if len(associated) > 1:
                    raise ValueError("Resolve multiple masks for " + item.path)
                result = assess_image(item.path, thresholds=config,
                    mask_path=associated[0].path if associated else None)
                if result["image_sha256"] != item.sha256:
                    raise ValueError("Image changed since inventory approval: " + item.path)
                if associated and result["mask_sha256"] != associated[0].sha256:
                    raise ValueError("Mask changed since inventory approval: " + associated[0].path)
                if result["decision"] != "keep":
                    result = assess_image(item.path, thresholds=config,
                        mask_path=associated[0].path if associated else None, artifact_dir=artifacts)
                results.append(result)
                if index % 100 == 0 or index + 1 == len(images):
                    self._emit("progress", stage="preprocess", current=index + 1, total=len(images), message="Checking local scene detail")
            assert_source_unchanged(items)
            payload = {"input_inventory_hash": approval_token(items), "tolerances": asdict(config),
                       "results": results, "excluded_paths": []}
            value = store.put("quality", payload, invalidate=("spatial", "selection"))
            schema = [{"key": f.name, "label": f.name.replace("_", " "),
                       "type": "bool" if type(getattr(config, f.name)) is bool else "int" if type(getattr(config, f.name)) is int else "float"}
                      for f in fields(config)]
            self._emit("image_quality", assessment_hash=value["assessment_hash"],
                candidates=[{"path": r["image_path"], **r} for r in results if r["decision"] != "keep"],
                tolerances=asdict(config), tolerance_schema=schema,
                summary={"images": len(results), "candidates": sum(r["candidate"] for r in results)})
        self._submit(project, "preprocess", scan)

    @_project_mutation
    def apply_image_culling(self, project, assessment_hash, excluded_paths, confirmed_by):
        self._idle()
        store = ReviewStore(project)
        value = store.read("quality")
        if (value["assessment_hash"] != assessment_hash or value.get("invalidated_by")
                or digest(value["payload"]) != assessment_hash):
            raise ValueError("Image assessment changed; review the new results")
        payload = value["payload"]
        known = {r["image_path"] for r in payload["results"]}
        if not set(excluded_paths) <= known:
            raise ValueError("Culling references an unassessed image")
        unresolved = [r for r in payload["results"] if not r["assessment_complete"] and r["image_path"] not in excluded_paths]
        if unresolved:
            raise ValueError("Corrupt or unassessed images must be resolved or explicitly excluded")
        payload["excluded_paths"] = sorted(set(excluded_paths))
        value = store.put("quality", payload, invalidate=("spatial", "selection"))
        store.approve("quality", value["assessment_hash"], confirmed_by)
        self._emit("state", stage="preprocess", state="quality_confirmed", ownership_released=True,
                   assessment_hash=value["assessment_hash"],
                   message="Image selection confirmed; dive-track density review is required before batching")

    def scan_spatial_review(self, project, options=None):
        def scan():
            from .navigation_quality import match_images
            from .spatial_review import assess_spatial, points_from_matches
            store = ReviewStore(project)
            items = store.inventory(approved=True)
            quality = store.require_approved("quality")["payload"]
            if quality["input_inventory_hash"] != approval_token(items):
                raise ValueError("Quality assessment predates the current inventory")
            for item in items:
                if item.path in quality["excluded_paths"]:
                    item.included = False
            nav, frame = self._navigation(project)
            matches = match_images(items, frame, self._values(project, "navigation").get("max_match_seconds", 2),
                include_excluded=True, clock_offset_seconds=self._values(project, "navigation").get("clock_offset_seconds", 0),
                cancelled=self._cancelled, progress=lambda current, total, path: self._emit("progress",
                    stage="preprocess", current=current, total=total, message="Matching images to the dive track"))
            required = {item.path for item in items if item.included and not item.duplicate_of and item.kind == "image"}
            unmatched = [row for row in matches["unmatched"] if row["path"] in required]
            if unmatched:
                self._emit("navigation", items=unmatched)
                raise ValueError(f"{len(unmatched)} retained images lack valid navigation; exclude or correct before batching")
            points = points_from_matches(items, frame, matches, epsg=nav["epsg"])
            assessment = assess_spatial(points, epsg=nav["epsg"], thresholds=options,
                                       track=frame[["kalman_x", "kalman_y"]].values.tolist())
            assessment["track_gap_seconds"] = 2.0
            assessment["track_segments"] = track_segments(frame, max_gap_seconds=2.0)
            payload = {"input_inventory_hash": quality["input_inventory_hash"],
                       "quality_selection_hash": digest(quality), "navigation_sha256": nav["sha256"],
                       "assessment": assessment, "excluded_paths": []}
            value = store.put("spatial", payload, invalidate=("selection",))
            self._emit("spatial_review", **{**assessment, "spatial_excluded_paths": [], "assessment_hash": value["assessment_hash"]})
        self._submit(project, "preprocess", scan)

    @_project_mutation
    def apply_spatial_culling(self, project, assessment_hash, excluded_paths, confirmed_by):
        self._idle()
        store = ReviewStore(project)
        value = store.read("spatial")
        if (value["assessment_hash"] != assessment_hash or value.get("invalidated_by")
                or digest(value["payload"]) != assessment_hash):
            raise ValueError("Spatial assessment changed; review the current plot")
        payload = value["payload"]
        known = {p["path"] for p in payload["assessment"]["points"]}
        if not set(excluded_paths) <= known:
            raise ValueError("Spatial culling references an image outside this assessment")
        payload["excluded_paths"] = sorted(set(excluded_paths))
        # A new selection needs a refreshed density plot and separate final gate.
        from .spatial_review import assess_spatial
        quality_excluded = set(store.require_approved("quality")["payload"]["excluded_paths"])
        base = {item.path: item for item in store.inventory(approved=True)}
        for point in payload["assessment"]["points"]:
            item = base[point["path"]]
            point["excluded"] = (not item.included or bool(item.duplicate_of)
                or point["path"] in quality_excluded or point["path"] in excluded_paths)
        assessment = payload["assessment"]
        payload["assessment"] = assess_spatial(assessment["points"], epsg=assessment["epsg"],
            thresholds=assessment["thresholds"], track=assessment["track"])
        for key in ("track_segments", "track_gap_seconds"):
            if key in assessment:
                payload["assessment"][key] = assessment[key]
        payload["selection_by"] = confirmed_by
        value = store.put("spatial", payload, invalidate=("selection",))
        self._emit("spatial_review", **{**payload["assessment"], "spatial_excluded_paths": payload["excluded_paths"],
                                      "assessment_hash": value["assessment_hash"]})

    @_project_mutation
    def confirm_spatial_review(self, project, assessment_hash, confirmed_by):
        self._idle()
        store = ReviewStore(project)
        assert_source_unchanged(store.inventory(approved=True))
        store.require_approved("quality")
        spatial = store.read("spatial")["payload"]
        navigation = store.read("navigation")["payload"]
        if spatial["navigation_sha256"] != navigation["sha256"]:
            raise ValueError("Navigation changed since the density review; rebuild the plot")
        self._navigation(project)  # Check the current artifact, not just metadata.
        store.approve("spatial", assessment_hash, confirmed_by)
        store.selection()  # Checks dependencies before the UI reports ready.
        self._finish_review_stage(project, "preprocess", store.read("spatial"))
        self._emit("state", stage="preprocess", state="selection_confirmed", ownership_released=True,
                   message="Culling and density review confirmed; approved selection may be batched")

    @staticmethod
    def _occlusion_event_data(project):
        from .project_occlusion import parameter_schema
        from .temporal_occlusion import TemporalMaskConfig
        store = ReviewStore(project)
        value = store.read("occlusion_review", required=False)
        event = {"kind": "occlusion_masks", "decision": "pending", "confirmed": False,
                 "parameters": asdict(TemporalMaskConfig()), "parameter_schema": parameter_schema(),
                 "groups": [], "assessment_hash": "", "batch_fingerprint": ""}
        if value:
            event.update(value["payload"])
            event["assessment_hash"] = value["assessment_hash"]
            event["confirmed"] = False
            if value["payload"].get("decision") in ("applied", "skipped"):
                try:
                    store.require_occlusion_review(value["payload"].get("batch_fingerprint"))
                except (ValueError, KeyError, TypeError, AttributeError) as exc:
                    event["message"] = str(exc)
                else:
                    event["confirmed"] = True
        return event

    def _invalidate_after_mask_change(self, project):
        # Keep prior attempts and outputs as provenance; never reuse their
        # alignment as if it had consumed a newly reviewed image mask set.
        project.restart_stage("align", "Post-batch ROV mask decision changed")
        project.save()

    def scan_occlusion_masks(self, project, options=None):
        def scan():
            from . import project_occlusion
            from .temporal_occlusion import TemporalMaskConfig
            config = TemporalMaskConfig(**(options or {}))
            config.validate()
            context = project_occlusion.context(project, cancelled=self._cancelled)
            self._invalidate_after_mask_change(project)
            store = ReviewStore(project)
            # Revoke prior approval before generation. Cancellation or a decode
            # failure cannot leave an older mask decision armed for alignment.
            store.put("occlusion_review", {"decision": "pending",
                "batch_fingerprint": context["batch_fingerprint"]})
            self._emit(**self._occlusion_event_data(project))
            payload = project_occlusion.generate(project, context, asdict(config),
                cancelled=self._cancelled, progress=self._occlusion_progress)
            store.put("occlusion_review", payload)
            self._emit(**self._occlusion_event_data(project))
        self._submit(project, "occlusion_masks", scan)

    def _occlusion_progress(self, phase, current, total, path):
        self._emit("progress", stage="occlusion_masks", phase=phase, current=current,
                   total=total, message=f"{phase}: {path}")

    def apply_occlusion_masks(self, project, assessment_hash, confirmed_by, *, accepted_block_ids=None):
        # Capture the UI's exact selection before handing it to the worker.
        # None retains the explicit all-candidates API; the UI supplies IDs.
        accepted = None if accepted_block_ids is None else tuple(accepted_block_ids)
        def apply():
            from . import project_occlusion
            store = ReviewStore(project)
            value = store.read("occlusion_review")
            if (value["assessment_hash"] != assessment_hash or value.get("invalidated_by")
                    or value["payload"].get("decision") != "generated"):
                raise ValueError("Mask assessment changed; review the current previews")
            if not isinstance(confirmed_by, str) or not confirmed_by.strip():
                raise ValueError("Mask approval requires an operator name")
            if accepted is not None:
                candidates = {group["group_id"] for group in value["payload"].get("groups", [])
                              if group.get("status") == "candidate_review_required"}
                if (not accepted or any(not isinstance(key, str) for key in accepted)
                        or len(set(accepted)) != len(accepted) or not set(accepted) <= candidates):
                    raise ValueError("Select reviewable mask blocks, or explicitly skip masking")
            context = project_occlusion.context(project, cancelled=self._cancelled)
            self._invalidate_after_mask_change(project)
            payload = project_occlusion.apply(project, context, value["payload"], confirmed_by,
                accepted_block_ids=accepted, cancelled=self._cancelled, progress=self._occlusion_progress)
            project_occlusion.validate(project, context, payload, cancelled=self._cancelled)
            value = store.put("occlusion_review", payload)
            store.approve("occlusion_review", value["assessment_hash"], confirmed_by)
            self._emit(**self._occlusion_event_data(project))
        self._submit(project, "occlusion_masks", apply)

    def skip_occlusion_masks(self, project, reason, confirmed_by):
        def skip():
            from . import project_occlusion
            if not isinstance(confirmed_by, str) or not confirmed_by.strip():
                raise ValueError("Skipping masking requires an operator name")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError("Skipping masking requires a reason")
            context = project_occlusion.context(project, cancelled=self._cancelled)
            self._invalidate_after_mask_change(project)
            store = ReviewStore(project)
            store.put("occlusion_review", {"decision": "pending",
                "batch_fingerprint": context["batch_fingerprint"]})
            payload = project_occlusion.skip(project, context, reason, confirmed_by,
                cancelled=self._cancelled, progress=self._occlusion_progress)
            project_occlusion.validate(project, context, payload, cancelled=self._cancelled)
            value = store.put("occlusion_review", payload)
            store.approve("occlusion_review", value["assessment_hash"], confirmed_by)
            self._emit(**self._occlusion_event_data(project))
        self._submit(project, "occlusion_masks", skip)

    def start(self, project, stage):
        if stage == "inventory":
            return self.scan_inventory(project)
        if stage == "preprocess":
            return self.scan_image_quality(project)
        if stage == "batch":
            # Deliberately before _submit: project.skip_stage cannot bypass this.
            ReviewStore(project).selection()
        self._submit(project, stage, lambda: self._run_stage(project, stage))

    @staticmethod
    def required_settings_blocks(stage):
        """One stage-to-settings map shared by execution and its UI summary."""
        if stage in ("inventory", "preprocess"):
            return []
        required = ["operating", "navigation"] if stage == "navigation" else ["operating", "navigation", "cameras", "science"]
        if stage in ("georeference", "batch", "align", "merge"):
            required.append(stage)
        if stage in ("align", "merge", "model", "export"):
            required.append("budget")
        return required

    def _run_stage(self, project, stage):
        required = self.required_settings_blocks(stage)
        attempt = project.start_stage(stage, required_blocks=required)
        try:
            project.save()
            evidence = self._execute_stage(project, stage)
            path = project.resolve_path(f"metadata/attempts/{attempt}/result.json")
            write_json(path, evidence)
            project.record_output(stage, path, attempt_id=attempt)
            project.complete_stage(stage, attempt_id=attempt)
        except OwnershipUnconfirmed:
            raise  # Keep the persisted attempt running until reconciliation.
        except Exception as exc:
            project.fail_stage(stage, str(exc), attempt_id=attempt)
            raise
        finally:
            project.save()
        if stage == "batch":
            self._emit(**self._occlusion_event_data(project))

    def _execute_stage(self, project, stage):
        from rs import execute_commands
        from .navigation_quality import assess_navigation
        from .run_plan import build_plan
        from .verify import verify_workspace
        store = ReviewStore(project)
        data = project.to_dict()
        if stage == "navigation":
            store.require_approved("inventory")
            before = set(project.resolve_path("proc/navigation").glob("*/navigation_result.json"))
            command = {"stage": "Navigation", "argv": [sys.executable,
                str(REPO / "integrations/rovdataconcat/navigation.py"), "--source", str(self._source(project)),
                "--project", str(project.root), "--expedition", data["expedition"], "--dive", data["dive"],
                "--reserve-gib", str(self._values(project, "operating").get("reserve_gib", 50)), "--execute"],
                "env": {"PYTHONIOENCODING": "utf-8"}, "needs_realityscan": False}
            label = self._record_execution_plan(project, stage, {"commands": [command]}, project.resolve_path("proc/_agent"))
            code = execute_commands([command], project.resolve_path("proc/_agent"), "",
                control=self._control, observer=self._observe, label=label)
            after = set(project.resolve_path("proc/navigation").glob("*/navigation_result.json")) - before
            if code or len(after) != 1:
                raise RuntimeError("Navigation run did not produce exactly one new result manifest")
            result = json.loads(next(iter(after)).read_text(encoding="utf-8"))
            path = Path(result["navigation"]).resolve()
            if not path.is_relative_to(project.root):
                raise ValueError("Navigation result escaped the project")
            quality = assess_navigation(path, data["expedition"], data["dive"])
            if not quality["structurally_valid"]:
                raise ValueError("Navigation validation failed: " + "; ".join(quality["errors"]))
            quality["relative_path"] = path.relative_to(project.root).as_posix()
            store.put("navigation", quality, invalidate=("spatial", "selection"))
            self._emit("navigation", items=[quality])
            return quality
        # _run_stage checks the blocks used by this step. Future-stage settings
        # must not force an operator to approve alignment before reviewing data.
        if not data["settings"]:
            raise ValueError("Apply and confirm processing settings before starting")
        if stage in ("align", "merge", "model", "export"):
            from .deployment_preflight import require_deployment
            from .storage_policy import StorageDemand
            operating = self._values(project, "operating")
            self.ensure_cache(project)
            budget = self._values(project, "budget")
            deployment = require_deployment(install_dir=operating["install_dir"], project_root=project.root,
                cache_root=operating["cache_dir"], reserve_gib=operating["reserve_gib"], probe_writes=True,
                protected_roots=data["sources"] + [project.resolve_path("raw")],
                demands=[StorageDemand(project.root, float(budget["disk_delta_gb"]), "project"),
                         StorageDemand(operating["cache_dir"], float(budget["cache_delta_gb"]), "cache")])
            self._emit("deployment", report=deployment)
        session, charter, context = self._prepare_session(project, stage)
        from .preflight import preflight_charter
        readiness = preflight_charter(charter, [stage])
        self._emit("preflight", **readiness)
        if readiness["verdict"] != "ready":
            raise ValueError("Preflight requires attention: " + "; ".join(readiness["blocking"] + [m["question"] for m in readiness["missing"]]))
        if stage == "merge":
            session, charter = self._prepare_merge_evidence(project, session, charter, context)
            readiness = preflight_charter(charter, [stage])
            self._emit("preflight", **readiness)
            if readiness["verdict"] != "ready":
                raise ValueError("Merge preflight changed after native proof: " + "; ".join(
                    readiness["blocking"] + [m["question"] for m in readiness["missing"]]))
        plan = build_plan(session, charter=charter)
        if not plan["commands"] or plan["warnings"] or any(c.get("parses") is False for c in plan["commands"]):
            raise ValueError("Processing plan requires correction: " + "; ".join(plan["warnings"]))
        attempt = uuid4().hex
        runtime = project.resolve_path("proc/tmp/" + attempt)
        operating = self._values(project, "operating")
        for record in plan["commands"]:
            record["env"].update(RS_RUN_ID=attempt, RS_RUNTIME_ROOT=str(runtime),
                RS_CONTROL_FILE=str(runtime / "control.json"), RS_EVENT_FILE=str(runtime / "runtime.jsonl"),
                RS_ERRORS_DIR=str(runtime / "markers"),
                RS_INSTANCE=operating["instance"], RS_CACHE_DIR=operating["cache_dir"],
                RS_PROJECT_FILE=str(project.path),
                RS_REQUIRE_NEW_INSTANCE="1", RS_EXECUTABLE=str(Path(operating["install_dir"]) / "RealityScan.exe"),
                RS_CAMERA_PRIORS_FILE=context["priors_file"], RS_SETTINGS_PATH=str(runtime / "settings.json"),
                RS_NO_SETTINGS_INHERITANCE="1")
            if context.get("selection_manifest"):
                record["env"]["RS_SELECTION_MANIFEST"] = context["selection_manifest"]
            if context.get("occlusion_manifest"):
                record["env"]["RS_OCCLUSION_MANIFEST"] = context["occlusion_manifest"]
                record["env"]["RS_OCCLUSION_MANIFEST_SHA256"] = context["occlusion_manifest_sha256"]
        label = self._record_execution_plan(project, stage, plan, Path(session.results_root) / "_agent")
        code = execute_commands(plan["commands"], Path(session.results_root) / "_agent", str(charter.path), session=session,
            control=self._control, observer=self._observe, label=label)
        if stage == "georeference":
            from .flight_logs import find_flight_log
            from .project_staging import filter_flight_log
            log = find_flight_log(context["images_root"])
            if code or not log:
                raise RuntimeError("Georeference did not create the required zone-tagged flight log")
            checked = filter_flight_log(log, project.resolve_path("proc/tmp/" + attempt + "/verified"),
                                       store.inventory(approved=True), expected_epsg=context["epsg"])
            result = {"input_inventory_hash": approval_token(store.inventory(approved=True)),
                      "flight_log": Path(log).relative_to(project.root).as_posix(),
                      "sha256": file_hash(Path(log)), "epsg": context["epsg"],
                      "validated_rows_sha256": file_hash(checked),
                      "settings_hash": project.settings_signature(GEO_SETTINGS_BLOCKS),
                      "settings_scope": list(GEO_SETTINGS_BLOCKS),
                      "navigation_sha256": context["navigation_sha256"]}
            store.put("georeference", result, invalidate=("quality", "spatial", "selection", "workflow"))
            return result
        verdict = verify_workspace(session.results_root, require=[stage])
        write_json(project.resolve_path("metadata/verifications/" + attempt + ".json"), verdict)
        if code or verdict["verdict"] != "ok":
            raise RuntimeError("Stage did not pass artifact verification; inspect the project logs")
        return verdict

    def _prepare_merge_evidence(self, project, session, charter, context):
        """Post-alignment proof through the normal recorded child/executor lane."""
        from rs import execute_commands
        from .orphan_import_evidence import ensure_orphan_import_evidence
        from .project_workspace import ProjectDocument
        from .run_charter import parse_charter
        from .run_plan import session_from_charter
        from .verify import verify_workspace

        required = self.required_settings_blocks("merge")
        signature = project.settings_signature(required)
        alignment_snapshot = project.to_dict()["stages"]["align"]
        merge_snapshot = project.to_dict()["stages"]["merge"]

        def assert_approved():
            if self._control.cancellation_requested:
                raise InterruptedError("Merge proof cancelled")
            saved = ProjectDocument.load(project.path)
            if (saved.project_id != project.project_id or saved.root != project.root
                    or not project.settings_approved(required) or not saved.settings_approved(required)
                    or project.settings_signature(required) != signature
                    or saved.settings_signature(required) != signature):
                raise ValueError("Saved merge settings/approval changed; review before native proof")
            alignment = saved.to_dict()["stages"]["align"]
            if (alignment != alignment_snapshot or project.to_dict()["stages"]["align"] != alignment_snapshot
                    or alignment["state"] != "succeeded" or not alignment["attempts"]):
                raise ValueError("Native orphan proof requires the current completed alignment")
            if (saved.to_dict()["stages"]["merge"] != merge_snapshot
                    or project.to_dict()["stages"]["merge"] != merge_snapshot):
                raise ValueError("Current merge attempt changed during native proof")
            attempt_id = alignment["attempts"][-1]["id"]
            outputs = [r for r in saved.verify_outputs("align") if r["valid"] and r["attempt_id"] == attempt_id]
            records = [r for r in saved.to_dict()["outputs"] if r["stage"] == "align" and r["valid"] and r["attempt_id"] == attempt_id]
            if not outputs or any(r["status"] != "ok" for r in outputs) or any(r["bytes"] <= 0 for r in records):
                raise ValueError("Current alignment output proof is missing or its content hash changed")
            verdict = verify_workspace(session.results_root, require=["align"])
            if verdict["verdict"] != "ok":
                raise ValueError("Current alignment artifacts did not pass verification")

        assert_approved()
        operating = self._values(project, "operating")
        environment = dict(RS_SELECTION_MANIFEST=context["selection_manifest"],
            RS_OCCLUSION_MANIFEST=context["occlusion_manifest"],
            RS_OCCLUSION_MANIFEST_SHA256=context["occlusion_manifest_sha256"],
            RS_PROJECT_FILE=str(project.path), RS_CAMERA_PRIORS_FILE=context["priors_file"],
            RS_INSTANCE=operating["instance"], RS_CACHE_DIR=operating["cache_dir"],
            RS_EXECUTABLE=str(Path(operating["install_dir"]) / "RealityScan.exe"),
            RS_REQUIRE_NEW_INSTANCE="1", RS_NO_SETTINGS_INHERITANCE="1", RS_NO_INTERACTIVE="1",
            PYTHONIOENCODING="utf-8")

        def record_executor(manifest):
            assert_approved()
            runtime_id = uuid4().hex
            runtime = project.resolve_path("proc/tmp/" + runtime_id)
            child_environment = dict(environment, RS_RUN_ID=runtime_id, RS_RUNTIME_ROOT=str(runtime),
                RS_CONTROL_FILE=str(runtime / "control.json"), RS_EVENT_FILE=str(runtime / "runtime.jsonl"),
                RS_ERRORS_DIR=str(runtime / "markers"), RS_SETTINGS_PATH=str(runtime / "settings.json"),
                RS_ORPHAN_EVIDENCE_CHILD="1")
            command = {"stage": "merge", "needs_realityscan": True, "cwd": str(REPO), "env": child_environment,
                "argv": [sys.executable, "-B", "-m", "modules.orphan_import_probe", "record", "--manifest",
                         manifest["path"], "--expected-sha256", manifest["sha256"], "--execute"]}
            probe_plan = {"commands": [command], "purpose": "orphan_import_readback"}
            agent_root = Path(manifest["path"]).parent / "_agent" / runtime_id
            label = self._record_execution_plan(project, "merge", probe_plan, agent_root)
            return execute_commands(probe_plan["commands"], agent_root, str(charter.path),
                control=self._control, observer=self._observe, label=label)

        selected = ReviewStore(project).selection()
        evidence = ensure_orphan_import_evidence(project_root=project.root,
            components_root=session.workspace().aligned, selection_manifest=context["selection_manifest"],
            policy_path=context["orphan_policy_path"], policy_sha256=file_hash(Path(context["orphan_policy_path"])),
            install_dir=operating["install_dir"], instance=operating["instance"],
            cache_dir=operating["cache_dir"], reserve_gib=operating["reserve_gib"],
            max_original_cameras=2 * len(selected), assert_approved=assert_approved,
            record_executor=record_executor, environment=environment,
            cancelled=self._cancelled, control=self._control,
            progress=lambda event: self._emit("progress", stage="merge", **event))
        assert_approved()
        if evidence is None:
            return session, charter
        policy = dict(context["orphan_policy"])
        policy["cli_probe_evidence"] = str(evidence)
        policy_path = project.resolve_path("metadata/merge_policies/" + digest(policy) + ".json")
        write_json(policy_path, policy)
        raw = copy.deepcopy(charter.raw)
        raw["science"]["orphan_policy"] = str(policy_path)
        charter_path = Path(charter.path).with_name("RUN_CHARTER_" + uuid4().hex + ".json")
        write_json(charter_path, raw)
        final_charter = parse_charter(raw, charter_path)
        return session_from_charter(final_charter, stages=["merge"]), final_charter

    def _prepare_session(self, project, stage):
        """Adapt approved data to run_plan; do not duplicate CLI construction."""
        if stage == "batch" and self._values(project, "batch").get("b_zone_layout", "copy") != "copy":
            raise ValueError("The native project workflow requires copy batch layout for post-batch mask review")
        from .navigation_quality import match_images
        from .project_staging import materialize_selection
        from .run_charter import parse_charter
        from .run_plan import session_from_charter, chain_arg_names
        from . import camera_registry
        store = ReviewStore(project)
        data = project.to_dict()
        operating = self._values(project, "operating")
        reserve = int(float(operating["reserve_gib"]) * GIB)
        nav, frame = self._navigation(project)
        items = store.inventory(approved=True)
        self._require_retired_source_masks(store, items)
        assert_source_unchanged(items)
        cameras = dict(self._values(project, "cameras"))
        priors = {"schema_version": 1, "orientation_weight": cameras.pop("orientation_weight"),
                  "defaults": cameras.pop("defaults", {}), "families": cameras,
                  "navigation": self._values(project, "navigation")}
        priors_path = project.resolve_path("metadata/priors/" + digest(priors) + ".json")
        write_json(priors_path, priors)
        camera_registry.load_project_priors(str(priors_path))
        context = {"priors_file": str(priors_path), "epsg": nav["epsg"], "navigation_sha256": nav["sha256"]}
        supplied = dict(self._values(project, stage))
        if stage == "georeference":
            nav_settings = self._values(project, "navigation")
            matches = match_images(items, frame, nav_settings["max_match_seconds"],
                                   clock_offset_seconds=nav_settings["clock_offset_seconds"],
                                   cancelled=self._cancelled, progress=lambda current, total, path: self._emit("progress",
                                       stage="georeference", current=current, total=total, message="Matching camera capture times"))
            if matches["unmatched"]:
                self._emit("navigation", items=matches["unmatched"])
                raise ValueError("Retained images lack navigation; correct or exclude the listed images")
            token = approval_token(items)
            intake = f"proc/intake/{token}/{uuid4().hex}"
            staged = stage_inventory(items, project.root, reserve_bytes=reserve, approved_token=token,
                images_relative_path=intake + "/images", cancelled=self._cancelled,
                progress=lambda current, total, message: self._emit("progress", stage=stage, current=current, total=total, message=message))
            context["images_root"] = staged["images_root"]
            root = project.resolve_path(intake)
            supplied.update(g_input=staged["images_root"], g_flight_log=str(project.resolve_path(nav["relative_path"])), g_type="All")
        else:
            selected = store.selection()
            spatial = store.require_approved("spatial")["payload"]
            if spatial["navigation_sha256"] != nav["sha256"]:
                raise ValueError("Navigation changed since density approval; review the current dive track")
            token = approval_token(selected)
            georeference = store.read("georeference")
            if georeference.get("invalidated_by"):
                raise ValueError("Georeference inputs/settings changed; rerun georeferencing")
            geo = georeference["payload"]
            if geo.get("input_inventory_hash") != approval_token(items):
                raise ValueError("Camera priors refer to a different source inventory; rerun georeferencing")
            if geo.get("navigation_sha256") != nav["sha256"]:
                raise ValueError("Camera priors were derived from different or unrecorded navigation; rerun georeferencing")
            log = project.resolve_path(geo["flight_log"])
            scope = geo.get("settings_scope")
            if scope is None:
                # Old records contain only a global hash. Never infer their
                # historical subset from values edited after the original run.
                expected_settings = project.settings_hash
            elif scope == list(GEO_SETTINGS_BLOCKS):
                expected_settings = project.settings_signature(GEO_SETTINGS_BLOCKS)
            else:
                raise ValueError("Unsupported georeference settings provenance; rerun georeferencing")
            if file_hash(log) != geo["sha256"] or geo["settings_hash"] != expected_settings:
                raise ValueError("Georeference inputs/settings changed; rerun georeferencing")
            if stage == "batch":
                manifest, manifest_path = materialize_selection(project, log, expected_epsg=nav["epsg"],
                    reserve_bytes=reserve, cancelled=self._cancelled,
                    progress=lambda current, total, message: self._emit("progress", stage=stage, current=current, total=total, message=message))
                root = project.resolve_path("proc/workflows/" + token)
                store.put("workflow", {"selection_hash": token, "root": root.relative_to(project.root).as_posix(),
                    "selection_manifest": manifest_path.relative_to(project.root).as_posix()})
                supplied.update(b_input=manifest["images_root"], b_flight_log_path=manifest["flight_log"])
            else:
                workflow = store.read("workflow")["payload"]
                if workflow["selection_hash"] != token:
                    raise ValueError("Workflow uses an obsolete image selection; batch the current selection first")
                root = project.resolve_path(workflow["root"])
                manifest_path = project.resolve_path(workflow["selection_manifest"])
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if file_hash(Path(manifest["flight_log"])) != manifest["flight_log_sha256"]:
                    raise ValueError("Selected flight log has changed")
                if stage == "align":
                    supplied.update(r_input=str(root / "batched_images_by_zone"), r_flight_log=manifest["flight_log"],
                                    r_project_label=f"{data['expedition']}_{data['dive']}")
                from . import project_occlusion
                decision = project_occlusion.validate(project, cancelled=self._cancelled,
                    progress=self._occlusion_progress)
                context["occlusion_manifest"] = str(project.resolve_path(decision["canonical_manifest"]))
                context["occlusion_manifest_sha256"] = decision["canonical_sha256"]
            context["selection_manifest"] = str(manifest_path)
            # Existing export/frame discovery reads this canonical workspace log.
            copy = root / "raw_images" / Path(manifest["flight_log"]).name
            from .source_inventory import copy_verified
            copy_verified(Path(manifest["flight_log"]), copy, expected_hash=manifest["flight_log_sha256"],
                          reserve_bytes=reserve, cancelled=self._cancelled)
        root.mkdir(parents=True, exist_ok=True)
        science = dict(self._values(project, "science"))
        science["frame"] = "utm:" + nav["utm_zone"]
        if stage == "merge":
            from merge_zones import validate_orphan_policy
            policy = dict(self._values(project, "merge"))
            policy.pop("cli_probe_evidence", None)  # Evidence is generated/replayed after alignment, never hand-supplied.
            validate_orphan_policy(policy)
            policy_path = project.resolve_path("metadata/merge_policies/" + digest(policy) + ".json")
            write_json(policy_path, policy)
            science["orphan_policy"] = str(policy_path)
            context.update(orphan_policy=policy, orphan_policy_path=str(policy_path), workflow_root=str(root))
            supplied = {}  # The canonical planner consumes the approved policy.
        if stage in ("georeference", "batch", "align"):
            allowed = chain_arg_names([stage])
            supplied = {key: value for key, value in supplied.items() if key in allowed}
        approved = next(block["approval"] for block in data["settings"].values() if block["approval"])
        raw = {"schema": 1, "campaign": data["expedition"], "dive": data["dive"],
            "locations": {"results_root": str(root), "originals": data["sources"],
                          "nav": [str(project.resolve_path(nav["relative_path"]))],
                          "protected": [{"path": str(project.resolve_path("raw")), "why": "Preserved source copies"}]},
            "ownership": {"rs_instance": operating["instance"], "rs_cache_dir": operating["cache_dir"], "user_instances": []},
            "budget": self._values(project, "budget"), "science": science,
            "pipeline": {"stages": [stage], "answers": supplied},
            "signed_off": {"by": approved["by"], "date": approved["at"], "quote": "Approved project settings and reviewed source selection"}}
        charter_path = root / "_agent" / ("RUN_CHARTER_" + uuid4().hex + ".json")
        write_json(charter_path, raw)
        charter = parse_charter(raw, charter_path)
        return session_from_charter(charter, stages=[stage]), charter, context
