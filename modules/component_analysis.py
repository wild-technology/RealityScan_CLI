#!/usr/bin/env python3
"""Pure component-set analysis over alignment manifests (schema v1).

No RealityScan interaction happens here. Input is the JSON manifests
written next to each exported .rsalign at zone-align time (see
docs/merge-growth-strategy-2026-07.md "Bookkeeping layer"):

    {"schema": 1, "zone": str, "component": str, "rsalign": str,
     "images": [basenames], "camera_count": int,
     "bbox_utm": [minx, miny, maxx, maxy] or null,
     "quality": {"mean_reproj_px": float or null},
     "created": iso8601, "history": [{"event": str, "at": iso8601}]}

Policy (FINDINGS.md "Twin components across zones"):
- A component with NO unique images (its image set fully covered by the
  union of the other components in its twin group) is discardable.
- A component with ANY unique images must NEVER be dropped.
- Merging is only attempted between components whose georeferenced
  areas border/overlap (bbox + margin); a null bbox means unknown, so
  the component stays a candidate against everything.

All functions are pure (dict in, dict out) except load_manifests, which
is a thin filesystem convenience for callers.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Iterable, Optional, Sequence

SCHEMA_VERSION = 1
MANIFEST_SUFFIX = ".manifest.json"

DEFAULT_CONTAINMENT_THRESHOLD = 0.95
DEFAULT_BORDER_MARGIN_M = 10.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def component_key(manifest: dict) -> str:
    """Stable human-readable identity for a component: 'zone/component'."""
    return "{0}/{1}".format(manifest.get("zone", "?"), manifest.get("component", "?"))


def _validate(manifests: Sequence[dict]) -> None:
    seen = set()
    for m in manifests:
        if m.get("schema") != SCHEMA_VERSION:
            raise ValueError(
                "unsupported manifest schema {0!r} for {1}".format(
                    m.get("schema"), component_key(m)))
        for field in ("zone", "component", "images", "camera_count"):
            if field not in m:
                raise ValueError(
                    "manifest {0} missing required field {1!r}".format(
                        component_key(m), field))
        key = component_key(m)
        if key in seen:
            raise ValueError("duplicate component identity {0}".format(key))
        seen.add(key)


def _image_set(manifest: dict) -> frozenset:
    return frozenset(manifest["images"])


def _quality(manifest: dict) -> Optional[float]:
    q = manifest.get("quality") or {}
    return q.get("mean_reproj_px")


def containment(inner: dict, outer: dict) -> float:
    """Fraction of `inner`'s images that also appear in `outer`.

    An empty inner image set is fully contained by definition (it holds
    no unique images), so it reports 1.0.
    """
    inner_set = _image_set(inner)
    if not inner_set:
        return 1.0
    return len(inner_set & _image_set(outer)) / len(inner_set)


def load_manifests(directory: str) -> list:
    """Load every *.manifest.json under `directory` (recursive).

    Filesystem convenience only -- all analysis functions take the
    resulting list of dicts.
    """
    manifests = []
    for root, _dirs, files in os.walk(directory):
        for name in sorted(files):
            if name.endswith(MANIFEST_SUFFIX):
                path = os.path.join(root, name)
                with open(path, "r", encoding="utf-8") as fh:
                    manifests.append(json.load(fh))
    return manifests


# ---------------------------------------------------------------------------
# Twin detection
# ---------------------------------------------------------------------------

def find_twins(manifests: Sequence[dict],
               containment_threshold: float = DEFAULT_CONTAINMENT_THRESHOLD) -> dict:
    """Detect twin components by image-set containment.

    A directed twin pair (contained -> container) exists when at least
    `containment_threshold` of the contained component's images also
    appear in the container. Pairs are classified:

    - "full": containment == 1.0 -- the contained component has no
      image absent from the container (discard candidate);
    - "partial": threshold <= containment < 1.0 -- overlapping twins,
      the contained component still holds unique images and must never
      be dropped on the basis of this pair alone.

    Cross-zone pairs are the primary target (the 20% batcher overlap
    band duplicated into adjacent zones), but within-zone pairs are
    detected identically and tagged via "cross_zone": false.

    Returns {"pairs": [...], "groups": [...]} where groups are the
    connected components of the twin-pair graph, each listing member
    keys sorted by camera_count descending.
    """
    _validate(manifests)
    by_key = {component_key(m): m for m in manifests}
    keys = sorted(by_key)

    pairs = []
    adjacency = {k: set() for k in keys}
    for i, key_a in enumerate(keys):
        for key_b in keys[i + 1:]:
            a, b = by_key[key_a], by_key[key_b]
            for inner, outer in ((a, b), (b, a)):
                frac = containment(inner, outer)
                if frac >= containment_threshold:
                    inner_unique = len(_image_set(inner) - _image_set(outer))
                    pairs.append({
                        "contained": component_key(inner),
                        "container": component_key(outer),
                        "containment": frac,
                        "classification": "full" if inner_unique == 0 else "partial",
                        "unique_images_in_contained": inner_unique,
                        "cross_zone": inner["zone"] != outer["zone"],
                    })
                    adjacency[key_a].add(key_b)
                    adjacency[key_b].add(key_a)

    groups = []
    visited = set()
    for key in keys:
        if key in visited or not adjacency[key]:
            continue
        stack, members = [key], set()
        while stack:
            k = stack.pop()
            if k in members:
                continue
            members.add(k)
            stack.extend(adjacency[k] - members)
        visited |= members
        ordered = sorted(
            members,
            key=lambda k: (-by_key[k]["camera_count"], k))
        groups.append({
            "members": ordered,
            "cross_zone": len({by_key[k]["zone"] for k in members}) > 1,
        })

    return {"pairs": pairs, "groups": groups}


# ---------------------------------------------------------------------------
# Keeper selection
# ---------------------------------------------------------------------------

def _zone_network_sizes(manifests: Iterable[dict]) -> dict:
    sizes = {}
    for m in manifests:
        sizes[m["zone"]] = sizes.get(m["zone"], 0) + m["camera_count"]
    return sizes


def _preference_rank(manifest: dict, zone_sizes: dict) -> tuple:
    """Sort key: best keeper first. Higher camera_count wins; then lower
    mean_reproj_px (missing quality ranks after any known quality);
    then larger zone network; then key for determinism."""
    quality = _quality(manifest)
    return (
        -manifest["camera_count"],
        (1, 0.0) if quality is None else (0, quality),
        -zone_sizes.get(manifest["zone"], 0),
        component_key(manifest),
    )


def choose_keeper(twin_group: Sequence[dict],
                  zone_network_sizes: Optional[dict] = None) -> dict:
    """Pick the keeper of a twin group and mark discardable members.

    Preference order: higher camera_count; tie-break by lower
    quality.mean_reproj_px when present (a component with no quality
    figure loses the tie-break to one with any figure); then the zone
    with the larger network (total cameras per zone -- pass
    `zone_network_sizes` computed over ALL manifests for a true global
    figure, otherwise it is computed from the group alone); finally the
    component key for determinism.

    A member is discarded ONLY if it holds no unique images relative to
    the union of the members still being kept (evaluated worst-first),
    guaranteeing every image basename survives in at least one kept
    component. Members with unique images are retained with reason.

    Returns {"keeper": key, "discards": [{"component", "reason"}],
             "retained": [{"component", "reason"}]}.
    """
    if not twin_group:
        raise ValueError("choose_keeper requires a non-empty twin group")
    _validate(twin_group)
    zone_sizes = (dict(zone_network_sizes) if zone_network_sizes
                  else _zone_network_sizes(twin_group))

    ranked = sorted(twin_group, key=lambda m: _preference_rank(m, zone_sizes))
    keeper = ranked[0]

    kept = {component_key(m): _image_set(m) for m in twin_group}
    discards, retained = [], []
    # Evaluate worst-first so weak twins fall before better ones.
    for m in reversed(ranked[1:]):
        key = component_key(m)
        others_union = frozenset().union(
            *(imgs for k, imgs in kept.items() if k != key)) \
            if len(kept) > 1 else frozenset()
        unique = _image_set(m) - others_union
        if unique:
            retained.append({
                "component": key,
                "reason": "holds {0} unique image(s) not covered by the "
                          "rest of the group -- never discardable".format(len(unique)),
            })
        else:
            discards.append({
                "component": key,
                "reason": "no unique images (fully covered by kept "
                          "components); lost keeper preference to {0} "
                          "(camera_count {1} vs {2})".format(
                              component_key(keeper),
                              m["camera_count"], keeper["camera_count"]),
            })
            del kept[key]

    # Report in preference order for readability.
    order = {component_key(m): i for i, m in enumerate(ranked)}
    discards.sort(key=lambda d: order[d["component"]])
    retained.sort(key=lambda r: order[r["component"]])
    return {
        "keeper": component_key(keeper),
        "discards": discards,
        "retained": retained,
    }


# ---------------------------------------------------------------------------
# Border / adjacency detection
# ---------------------------------------------------------------------------

def _bboxes_border(bbox_a: Optional[Sequence[float]],
                   bbox_b: Optional[Sequence[float]],
                   margin_m: float) -> Optional[str]:
    """Reason string when the margin-expanded bboxes intersect, else None.

    A null bbox is unknown extent: it borders everything ("unknown_bbox").
    """
    if bbox_a is None or bbox_b is None:
        return "unknown_bbox"
    ax0, ay0, ax1, ay1 = bbox_a
    bx0, by0, bx1, by1 = bbox_b
    if (ax0 - margin_m <= bx1 + margin_m and bx0 - margin_m <= ax1 + margin_m and
            ay0 - margin_m <= by1 + margin_m and by0 - margin_m <= ay1 + margin_m):
        return "bbox_overlap_within_margin"
    return None


def find_borders(manifests: Sequence[dict],
                 margin_m: float = DEFAULT_BORDER_MARGIN_M) -> list:
    """Pairs of components whose margin-expanded UTM bboxes intersect.

    These are the only pairs merging should be attempted between.
    Components with bbox_utm null have unknown extent and pair with
    everything (reason "unknown_bbox").

    Returns a list of {"pair": [key_a, key_b], "reason": str,
    "cross_zone": bool} with key_a < key_b, deterministic order.
    """
    _validate(manifests)
    by_key = {component_key(m): m for m in manifests}
    keys = sorted(by_key)
    borders = []
    for i, key_a in enumerate(keys):
        for key_b in keys[i + 1:]:
            a, b = by_key[key_a], by_key[key_b]
            reason = _bboxes_border(a.get("bbox_utm"), b.get("bbox_utm"), margin_m)
            if reason:
                borders.append({
                    "pair": [key_a, key_b],
                    "reason": reason,
                    "cross_zone": a["zone"] != b["zone"],
                })
    return borders


# ---------------------------------------------------------------------------
# Orphans
# ---------------------------------------------------------------------------

def orphan_images(manifests: Sequence[dict], all_images: Iterable[str]) -> list:
    """Basenames from `all_images` registered in no component.

    Orphans stay in every merge scene as potential links (strategy doc
    section 6) -- this is the list to keep enabled.
    """
    _validate(manifests)
    covered = set()
    for m in manifests:
        covered |= _image_set(m)
    return sorted(set(all_images) - covered)


# ---------------------------------------------------------------------------
# Merge plan
# ---------------------------------------------------------------------------

def merge_plan(manifests: Sequence[dict],
               containment_threshold: float = DEFAULT_CONTAINMENT_THRESHOLD,
               margin_m: float = DEFAULT_BORDER_MARGIN_M,
               all_images: Optional[Iterable[str]] = None,
               zone_network_sizes: Optional[dict] = None) -> dict:
    """Full analysis pass: twins resolved first, then border-gated
    cross-zone merge candidates ordered largest-first.

    Steps (mirrors docs/merge-growth-strategy-2026-07.md steps 5-9):
    1. find_twins + choose_keeper per group -> discard list (only
       components with zero unique images relative to their group).
    2. Survivors are border-tested (bbox + margin; null bbox pairs with
       everything).
    3. Cross-zone bordering pairs become merge candidates, ordered by
       combined camera_count descending (largest-first). Within-zone
       bordering pairs are reported separately -- within-zone growth is
       merge_zones.py's job, not cross-zone merging.

    Returns a JSON-serializable dict with a reason on every decision.
    """
    _validate(manifests)
    by_key = {component_key(m): m for m in manifests}
    zone_sizes = (dict(zone_network_sizes) if zone_network_sizes
                  else _zone_network_sizes(manifests))

    twins = find_twins(manifests, containment_threshold)

    twin_resolutions = []
    discarded = set()
    for group in twins["groups"]:
        members = [by_key[k] for k in group["members"]]
        decision = choose_keeper(members, zone_network_sizes=zone_sizes)
        twin_resolutions.append({
            "members": group["members"],
            "cross_zone": group["cross_zone"],
            "keeper": decision["keeper"],
            "discards": decision["discards"],
            "retained": decision["retained"],
        })
        discarded |= {d["component"] for d in decision["discards"]}

    survivors = [m for m in manifests if component_key(m) not in discarded]
    borders = find_borders(survivors, margin_m)

    def pair_size(entry):
        return sum(by_key[k]["camera_count"] for k in entry["pair"])

    candidates, within_zone = [], []
    for entry in sorted(borders, key=lambda e: (-pair_size(e), e["pair"])):
        record = {
            "pair": entry["pair"],
            "combined_camera_count": pair_size(entry),
            "reason": entry["reason"],
        }
        if entry["cross_zone"]:
            candidates.append(record)
        else:
            within_zone.append(record)
    for priority, record in enumerate(candidates, start=1):
        record["priority"] = priority

    plan = {
        "schema": 1,
        "generated": datetime.now(timezone.utc).isoformat(),
        "parameters": {
            "containment_threshold": containment_threshold,
            "margin_m": margin_m,
        },
        "components": sorted(by_key),
        "twin_resolutions": twin_resolutions,
        "discards": sorted(discarded),
        "merge_candidates": candidates,
        "within_zone_border_pairs": within_zone,
    }
    if all_images is not None:
        plan["orphan_images"] = orphan_images(manifests, all_images)
    return plan
