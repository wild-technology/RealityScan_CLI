"""Per-feature merge planning (PRODUCT_READINESS must-fix 1 groundwork).

The delivery target is ONE unified component per major surveyed feature
(ON2026: hull, two masts, a stern flag-pole), and the machine constraint
is the merge-scene camera ceiling (C-20260802-01: ~34k cameras fit in
192 GB; ~44k died). This module is the PURE planning layer between the
two: 3D component extents from the navigation solution, assignment of
zone components to operator-defined feature boxes, and ceiling-aware
staged merge plans. Drivers consume the plan; nothing here launches
RealityScan.

3D on purpose: component manifests' bbox_utm is 2D, which is exactly why
the merge pair gate mis-classifies vertically separated structure
(mast-top over hull). Extents here carry Z from the nav log.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


def load_nav_positions(flight_log_path: str) -> dict:
    """Image basename -> (x, y, z) from a 13/4-column ;-separated flight
    log (header ignored). Rows without a numeric position are skipped."""
    nav: dict = {}
    with open(flight_log_path, encoding="utf-8-sig") as fh:
        first = True
        for line in fh:
            parts = line.rstrip("\r\n").split(";")
            if first:
                first = False
                # header row (the batcher convention) - skip if non-numeric
                try:
                    float(parts[1])
                except (ValueError, IndexError):
                    continue
            if len(parts) < 4:
                continue
            try:
                nav[parts[0].strip('"')] = (float(parts[1]), float(parts[2]),
                                            float(parts[3]))
            except ValueError:
                continue
    return nav


def component_extent(members: list, nav: dict) -> dict | None:
    """3D bbox + centroid of a component's member cameras. None when no
    member has a nav position (an extent must never be invented)."""
    pts = [nav[m] for m in members if m in nav]
    if not pts:
        return None
    xs, ys, zs = zip(*pts)
    n = len(pts)
    return {
        "bbox": [min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)],
        "centroid": [sum(xs) / n, sum(ys) / n, sum(zs) / n],
        "with_nav": n, "members": len(members),
    }


@dataclass
class FeatureBox:
    """Operator-defined spatial gate for one surveyed feature. None bounds
    are unbounded. Boxes are evaluated in order - put specific features
    (masts, flag-pole) BEFORE the catch-all hull."""
    name: str
    xmin: float | None = None
    xmax: float | None = None
    ymin: float | None = None
    ymax: float | None = None
    zmin: float | None = None
    zmax: float | None = None

    def contains(self, p) -> bool:
        x, y, z = p
        for lo, v, hi in ((self.xmin, x, self.xmax),
                          (self.ymin, y, self.ymax),
                          (self.zmin, z, self.zmax)):
            if lo is not None and v < lo:
                return False
            if hi is not None and v > hi:
                return False
        return True


def load_feature_boxes(path: str) -> tuple:
    """(boxes, default_feature, confirmed) from features.json. The file is
    an OPERATOR artifact - drivers must refuse to run while
    'confirmed' is false (pre-flight discipline: the feature geometry is
    a scientific choice, not a tool default)."""
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    boxes = [FeatureBox(name=b["name"],
                        **{k: b.get(k) for k in
                           ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")})
             for b in doc["features"]]
    return boxes, doc.get("default_feature", "hull"), bool(doc.get("confirmed"))


def assign_components(components: list, nav: dict, boxes: list,
                      default_feature: str = "hull") -> dict:
    """{feature_name: [component dict, ...]} by centroid-in-box, first
    matching box wins. Components without nav extent go to
    '_unassigned' - never silently to the default (an unlocatable
    component is a finding, not hull filler).

    Each input component dict needs: key, rsalign, camera_count, members.
    The returned dicts gain 'extent'.
    """
    out: dict = {b.name: [] for b in boxes}
    out.setdefault(default_feature, [])
    out["_unassigned"] = []
    for comp in components:
        ext = component_extent(comp.get("members") or [], nav)
        comp = dict(comp, extent=ext)
        if ext is None:
            out["_unassigned"].append(comp)
            continue
        for box in boxes:
            if box.contains(ext["centroid"]):
                out[box.name].append(comp)
                break
        else:
            out[default_feature].append(comp)
    return out


@dataclass
class MergeStage:
    """One merge invocation: the components entering the scene together."""
    components: list
    est_scene_cameras: int = 0


def plan_feature_merge(comps: list, ceiling: int) -> list:
    """Merge plan for ONE feature under the scene-camera ceiling.

    HONEST BY DESIGN (its own test killed a staged-growth fiction,
    2026-08-08): merged camera counts are ADDITIVE - duplicate-path zone
    overlap cameras persist through fusion - so any multi-stage
    fold-into-core sequence still ends with a final scene holding ~the
    feature's total. A feature whose total exceeds the ceiling therefore
    CANNOT be unified by any merge plan; that is an operator decision
    (redraw the feature boxes, or revisit the ceiling with the memory
    monitor armed - 34,105 cams measured 262 GB peak of the 192 GB box's
    ~320 GB commit budget, C-20260802-01), and this function refuses
    rather than pretending.
    """
    if not comps:
        return []
    total = sum(c["camera_count"] for c in comps)
    if total <= ceiling:
        return [MergeStage(components=list(comps), est_scene_cameras=total)]
    raise ValueError(
        f"feature total {total:,} cameras exceeds the {ceiling:,}-camera "
        "merge-scene ceiling and camera counts are additive through fusion "
        "- no merge sequence can unify it. Operator options: redraw the "
        "feature boxes (move boundary zones to a neighbouring feature), or "
        "raise --max_scene_cameras deliberately (measured envelope: 34,105 "
        "cams = 262 GB peak; 43,847 cams = OOM at 319.5 GB).")
