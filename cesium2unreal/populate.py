"""Populate an Unreal level with Cesium ion tilesets, snapped to an ion terrain.

Run from the Unreal editor's Python console:

    import sys; sys.path.append(r"C:\path\to\RealityScan_CLI")
    from cesium2unreal import populate
    populate.run("config.json")

The level, its CesiumGeoreference and its terrain tileset must already exist —
this script never creates or moves the georeference, because doing so would
slide every tileset relative to terrain that was authored in Unreal
coordinates. It only adds model tilesets and corrects their height.

This must run in an editor that is ticking. Cesium's height sampler is
asynchronous: it loads the terrain tiles it needs on demand and calls back
several frames later, so the work is driven from a post-tick callback rather
than running straight through. A `-run=pythonscript` commandlet has no tick
loop and will time out at the sampling step.
"""

import json
import math
import os
import statistics
import time

import unreal

from . import ion_locate

# The async action and its tick handle have to outlive run(); nothing else in
# the editor holds a reference and they would otherwise be collected mid-flight.
_PENDING = {}


# --------------------------------------------------------------------------
# level inspection
# --------------------------------------------------------------------------

def _actors():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()


def require_georeference():
    """The level's existing origin. Never modified — see the module docstring."""
    found = [a for a in _actors() if isinstance(a, unreal.CesiumGeoreference)]
    if not found:
        raise RuntimeError(
            "no CesiumGeoreference in this level. Add one and set its origin to "
            "match the terrain before running this script."
        )
    if len(found) > 1:
        unreal.log_warning(
            "%d CesiumGeoreference actors found; using %s"
            % (len(found), found[0].get_actor_label())
        )
    return found[0]


def find_tileset(asset_id=None, label=None):
    for a in _actors():
        if not isinstance(a, unreal.Cesium3DTileset):
            continue
        if asset_id is not None and int(a.get_editor_property("ion_asset_id")) == int(asset_id):
            return a
        if label is not None and a.get_actor_label() == label:
            return a
    return None


def require_terrain(cfg):
    terrain = find_tileset(
        asset_id=cfg.get("terrain_ion_asset_id"), label=cfg.get("terrain_actor_label")
    )
    if terrain is None:
        raise RuntimeError(
            "terrain tileset not found. Set terrain_ion_asset_id or "
            "terrain_actor_label in the config to a Cesium3DTileset already in "
            "the level."
        )
    if not terrain.get_editor_property("create_physics_meshes"):
        # Height sampling does not need physics meshes, but anything else that
        # traces against the seafloor will, and it is cheap to notice here.
        unreal.log_warning(
            "terrain '%s' has CreatePhysicsMeshes off — height sampling still "
            "works, but line traces against it will not hit anything."
            % terrain.get_actor_label()
        )
    return terrain


# --------------------------------------------------------------------------
# authoring
# --------------------------------------------------------------------------

def ensure_tileset(entry, georef, template=None):
    """Spawn or rebind one model tileset. Idempotent on the ion asset ID.

    The actor is created at the origin: a tileset carries its own ECEF root
    transform, so the georeference alone decides where it lands. The only
    reason this script moves an actor afterwards is the height correction.
    """
    asset_id = int(entry["id"])
    tileset = find_tileset(asset_id=asset_id)
    if tileset is None:
        tileset = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).spawn_actor_from_class(
            template or unreal.Cesium3DTileset,
            unreal.Vector(0.0, 0.0, 0.0),
            unreal.Rotator(0.0, 0.0, 0.0),
        )

    tileset.set_actor_label(str(entry.get("name", asset_id)))
    tileset.set_editor_property("tileset_source", unreal.TilesetSource.FROM_CESIUM_ION)
    tileset.set_editor_property("ion_asset_id", asset_id)
    tileset.set_editor_property("georeference", georef)
    tileset.set_editor_property("create_physics_meshes", True)
    return tileset


def apply_height(tileset, georef, lon, lat, height_from, height_to):
    """Shift a tileset vertically from one ellipsoidal height to another.

    Done as the difference between two georeferenced points rather than a raw
    Z nudge: "up" is only the Unreal +Z axis at the georeference origin, and
    diverges from it with distance. Letting the georeference convert both
    endpoints keeps the offset along the local vertical wherever the site is.
    """
    a = georef.transform_longitude_latitude_height_position_to_unreal(
        unreal.Vector(lon, lat, height_from)
    )
    b = georef.transform_longitude_latitude_height_position_to_unreal(
        unreal.Vector(lon, lat, height_to)
    )
    offset = unreal.Vector(b.x - a.x, b.y - a.y, b.z - a.z)
    tileset.set_actor_location(offset, False, False)
    return offset


# --------------------------------------------------------------------------
# clustering and stacking
# --------------------------------------------------------------------------

_EARTH_R = 6371008.8            # mean radius; clustering does not need better


def ground_distance_m(a, b):
    """Great-circle distance between two manifest entries, in metres."""
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp = p2 - p1
    dl = math.radians(b["lon"] - a["lon"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2.0 * _EARTH_R * math.asin(math.sqrt(h))


def cluster_sites(sites, radius_m=None):
    """Group sites whose footprints overlap. Returns a list of lists.

    With no radius given, two sites cluster when their bounding footprints
    actually intersect — the radii come from each tileset's own root bounding
    volume, so there is no threshold to guess. Pass radius_m to override with
    a fixed separation instead. Grouping is single-link: A-B and B-C puts all
    three in one cluster, which is what overlapping survey passes look like.
    """
    parent = list(range(len(sites)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(sites)):
        for j in range(i + 1, len(sites)):
            reach = (radius_m if radius_m is not None
                     else sites[i].get("radius_m", 0.0) + sites[j].get("radius_m", 0.0))
            if ground_distance_m(sites[i], sites[j]) <= reach:
                parent[find(i)] = find(j)

    groups = {}
    for i, site in enumerate(sites):
        groups.setdefault(find(i), []).append(site)
    return list(groups.values())


def _extent(site):
    """(below, above) — how far the model reaches from its own centre."""
    h = site["height"]
    return h - site.get("height_min", h), site.get("height_max", h) - h


def plan_cluster(members, terrain, gap_m=0.0):
    """Where each member of one cluster should end up.

    Snapping every overlapping model to the same terrain surface buries them
    in each other. Instead the deepest one is snapped to the terrain and the
    rest are stacked on top of it in depth order, each resting on the one
    below. A cluster of one reduces to a plain snap.

    terrain maps asset id -> sampled height, or None where sampling failed.
    Returns {id: (target_centre_height, placement)}; placement is "terrain"
    for the anchor, "stacked" above it, "unsampled" for members with no
    terrain under them, which are left where ion put them.
    """
    plan = {}
    eligible = sorted(
        [m for m in members if terrain.get(m["id"]) is not None],
        key=lambda m: m.get("height_min", m["height"]),
    )
    for m in members:
        if terrain.get(m["id"]) is None:
            plan[m["id"]] = (m["height"], "unsampled")

    if not eligible:
        return plan

    anchor = eligible[0]
    centre = terrain[anchor["id"]]
    plan[anchor["id"]] = (centre, "terrain")
    top = centre + _extent(anchor)[1]

    for m in eligible[1:]:
        below, above = _extent(m)
        centre = top + gap_m + below
        plan[m["id"]] = (centre, "stacked")
        top = centre + above

    return plan


# --------------------------------------------------------------------------
# asynchronous height sampling
# --------------------------------------------------------------------------

def sample_heights(terrain, positions, on_complete, timeout_s=300.0):
    """Batch-sample terrain heights at cartographic positions, then call back.

    Cesium's sampler is exposed only as a Blueprint async node: its factory and
    Activate are flagged BlueprintInternalUseOnly, which means the Python
    binding generator gives them no snake_case method. They are still reachable
    through the generic reflection invoker, call_method().
    """
    cls = getattr(unreal, "CesiumSampleHeightMostDetailedAsyncAction", None)
    if cls is None:
        raise RuntimeError(
            "CesiumSampleHeightMostDetailedAsyncAction is not in the unreal "
            "module. Check the Cesium for Unreal plugin is enabled and is "
            "v2.21.0 or later."
        )

    action = unreal.get_default_object(cls).call_method(
        "SampleHeightMostDetailed", (terrain, positions)
    )

    started = time.time()

    def finish(results, warnings):
        if _PENDING.get("handle") is not None:
            unreal.unregister_slate_post_tick_callback(_PENDING.pop("handle"))
        _PENDING.pop("action", None)
        for w in warnings or []:
            unreal.log_warning("height sampling: %s" % w)
        on_complete(results)

    def watchdog(_delta_seconds):
        if time.time() - started > timeout_s:
            handle = _PENDING.pop("handle", None)
            if handle is not None:
                unreal.unregister_slate_post_tick_callback(handle)
            _PENDING.pop("action", None)
            unreal.log_error(
                "height sampling timed out after %.0f s with %d positions. The "
                "editor must stay focused and ticking while tiles load."
                % (timeout_s, len(positions))
            )

    action.on_heights_sampled.add_callable(finish)
    _PENDING["action"] = action
    _PENDING["handle"] = unreal.register_slate_post_tick_callback(watchdog)
    action.call_method("Activate")
    return action


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def _summarise(rows):
    """Report the correction applied to terrain-anchored models.

    Snapping every model to the terrain hides a systematic height error by
    construction. A tight cluster of similar offsets is the signature of one —
    a geoid/ellipsoid mismatch shifts everything by nearly the same amount,
    whereas genuinely wrong placements scatter.
    """
    # Only terrain-anchored models carry datum evidence: a stacked model's
    # offset is dictated by whatever is beneath it, not by the seafloor.
    deltas = [r["delta_m"] for r in rows if r["placement"] == "terrain"]
    if not deltas:
        return {"anchored": 0}
    summary = {
        "anchored": len(deltas),
        "mean_m": statistics.fmean(deltas),
        "median_m": statistics.median(deltas),
        "min_m": min(deltas),
        "max_m": max(deltas),
        "stdev_m": statistics.stdev(deltas) if len(deltas) > 1 else 0.0,
    }
    if summary["anchored"] > 2 and summary["stdev_m"] < 1.0 and abs(summary["mean_m"]) > 2.0:
        unreal.log_warning(
            "every asset moved by %.1f m +/- %.1f m. That is a datum offset, "
            "not scattered placement error — worth fixing in ion rather than "
            "re-snapping on every import."
            % (summary["mean_m"], summary["stdev_m"])
        )
    return summary


def run(config_path):
    with open(config_path) as fh:
        cfg = json.load(fh)

    if cfg.get("level"):
        unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).load_level(cfg["level"])

    georef = require_georeference()
    terrain = require_terrain(cfg)

    cached = cfg.get("manifest")
    if cached and os.path.exists(cached):
        with open(cached) as fh:
            manifest = json.load(fh)
    else:
        token = os.environ[cfg.get("token_env", "CESIUM_ION_TOKEN")]
        manifest = ion_locate.build_manifest(token, cfg.get("name_pattern"))
        if cached:
            with open(cached, "w") as fh:
                json.dump(manifest, fh, indent=2)

    sites = [m for m in manifest if "error" not in m]
    for bad in [m for m in manifest if "error" in m]:
        unreal.log_warning("could not locate ion asset %s: %s" % (bad["id"], bad["error"]))
    if not sites:
        raise RuntimeError("no locatable ion assets matched %r" % cfg.get("name_pattern"))

    terrain_id = terrain.get_editor_property("ion_asset_id")
    sites = [s for s in sites if int(s["id"]) != int(terrain_id)]

    placed = [(s, ensure_tileset(s, georef)) for s in sites]
    unreal.log("placed %d tilesets; sampling terrain heights" % len(placed))

    positions = [unreal.Vector(s["lon"], s["lat"], s["height"]) for s, _ in placed]

    def on_sampled(results):
        terrain = {}
        for (site, _), result in zip(placed, results):
            ok = bool(result.get_editor_property("sample_success"))
            llh = result.get_editor_property("longitude_latitude_height")
            terrain[site["id"]] = llh.z if ok else None

        actors = {site["id"]: tileset for site, tileset in placed}
        sites = [site for site, _ in placed]
        if cfg.get("stack_clusters", True):
            groups = cluster_sites(sites, cfg.get("cluster_radius_m"))
        else:
            groups = [[site] for site in sites]
        gap = float(cfg.get("stack_gap_m", 0.0))

        rows = []
        # Largest clusters first, so the interesting ones head the report.
        for index, members in enumerate(sorted(groups, key=lambda g: -len(g))):
            plan = plan_cluster(members, terrain, gap)
            order = [m["id"] for m in sorted(
                (m for m in members if plan[m["id"]][1] != "unsampled"),
                key=lambda m: m.get("height_min", m["height"]))]

            for site in members:
                target, placement = plan[site["id"]]
                if placement == "unsampled":
                    unreal.log_warning(
                        "no terrain under '%s' (%.6f, %.6f) — left at its ion height"
                        % (site["name"], site["lat"], site["lon"])
                    )
                else:
                    apply_height(actors[site["id"]], georef, site["lon"],
                                 site["lat"], site["height"], target)
                rows.append({
                    "id": site["id"],
                    "name": site["name"],
                    "lon": site["lon"],
                    "lat": site["lat"],
                    "ion_height_m": site["height"],
                    "terrain_height_m": terrain[site["id"]],
                    "target_height_m": target,
                    "delta_m": target - site["height"],
                    "placement": placement,
                    "cluster": index if len(members) > 1 else None,
                    "stack_index": order.index(site["id"]) if site["id"] in order else None,
                    "sampled": terrain[site["id"]] is not None,
                })

        stacked = sum(1 for r in rows if r["placement"] == "stacked")
        clusters = sum(1 for g in groups if len(g) > 1)
        if stacked:
            unreal.log(
                "%d models in %d cluster(s) stacked above their deepest member; "
                "only the deepest sits on the terrain"
                % (stacked + clusters, clusters)
            )

        report = {"summary": _summarise(rows), "assets": rows}
        if cfg.get("report"):
            with open(cfg["report"], "w") as fh:
                json.dump(report, fh, indent=2)
            unreal.log(
            "%d of %d anchored to terrain, %d stacked; %s"
            % (report["summary"].get("anchored", 0), len(rows), stacked,
               json.dumps(report["summary"]))
        )

        unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
        unreal.log("done — level saved")

    sample_heights(terrain, positions, on_sampled,
                   timeout_s=float(cfg.get("timeout_s", 300)))
    unreal.log("sampling started; keep the editor focused until 'done' appears")
