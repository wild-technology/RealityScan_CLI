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
# clustering and the seafloor datum correction
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


def _deepest_point(site):
    """The model's lowest point, metres above the ellipsoid."""
    return site.get("height_min", site["height"])


def bounding_volume_lift(site, terrain_height):
    """How far to raise a model so its lowest point reaches the seafloor.

    Cheap and needs no extra sampling, but height_min is an extremum straight
    off the root bounding volume: one stray vertex at the bottom of a model
    drags its lift up and shifts the whole group with it.

    The planned robust alternative, `surface_percentile`, samples a grid across
    the model's footprint against both the terrain tileset and the model's own
    tileset — SampleHeightMostDetailed already does exactly this, so the
    machinery is in place — and takes a high percentile of the per-point
    residual rather than its maximum. Ground points give the largest residuals
    (the model surface is at its lowest there); structure sits above and gives
    smaller ones, so a high percentile still finds the ground while a single
    bad vertex no longer decides the answer. It costs one extra batch of
    samples per model, which is why it is not the default.
    """
    return terrain_height - _deepest_point(site)


DEPTH_ANCHORS = {"bounding_volume": bounding_volume_lift}


def plan_cluster(members, terrain, clearance_m=0.0, lift_fn=None):
    """One rigid vertical correction for a group of overlapping models.

    The multibeam surface is the ground truth for depth: nothing sits below
    it. For each member the lift needed to raise its deepest point to the
    seafloor beneath it is `terrain - height_min`; the cluster takes the
    largest of those, so the model that most violates the seafloor ends up
    resting exactly on it and no other member is left buried.

    That single correction is then applied to every member, which is the whole
    point. Moving each model onto the surface independently, or stacking them
    into contact, would flatten real vertical structure — a seawall is
    genuinely several metres above the seafloor its neighbour sits on, and
    those relative offsets are survey measurements, not artefacts. A rigid
    shift fixes the datum without touching the geometry between models.

    lift_fn decides how far one model must rise to meet the seafloor; see
    DEPTH_ANCHORS. terrain maps asset id -> sampled height, or None where
    sampling failed. Returns {id: (target_centre_height, placement)}:

      anchor     the member that defines the shift; rests on the seafloor
      offset     sampled member carried by the same shift, its depth relative
                 to the anchor preserved exactly
      carried    no terrain of its own, but corrected with its cluster —
                 better than leaving it on an uncorrected datum
      unsampled  no member of the cluster found terrain; left where ion put it
    """
    lift_fn = lift_fn or bounding_volume_lift
    lifts = {
        m["id"]: lift_fn(m, terrain[m["id"]])
        for m in members
        if terrain.get(m["id"]) is not None
    }
    if not lifts:
        return {m["id"]: (m["height"], "unsampled") for m in members}

    anchor_id = max(lifts, key=lifts.get)
    delta = lifts[anchor_id] + clearance_m

    plan = {}
    for m in members:
        if m["id"] == anchor_id:
            placement = "anchor"
        elif m["id"] in lifts:
            placement = "offset"
        else:
            placement = "carried"
        plan[m["id"]] = (m["height"] + delta, placement)
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
    """Report the per-cluster seafloor correction.

    Snapping every model to the terrain hides a systematic height error by
    construction. A tight cluster of similar offsets is the signature of one —
    a geoid/ellipsoid mismatch shifts everything by nearly the same amount,
    whereas genuinely wrong placements scatter.
    """
    # One lift per cluster: every other member moved by the same amount, so
    # counting them would report the same correction many times over.
    deltas = [r["delta_m"] for r in rows if r["placement"] == "anchor"]
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
    # A group whose correction disagrees with every other group is the
    # signature of a bad height_min — one stray vertex deciding the shift.
    # That is the case surface_percentile anchoring exists to fix.
    if len(deltas) > 3:
        median = statistics.median(deltas)
        spread = statistics.median([abs(d - median) for d in deltas]) or 1e-9
        for row in rows:
            if row["placement"] == "anchor" and abs(row["delta_m"] - median) > 6.0 * spread:
                summary.setdefault("outliers", []).append(
                    {"id": row["id"], "name": row["name"], "delta_m": row["delta_m"],
                     "median_delta_m": median})
        for o in summary.get("outliers", []):
            unreal.log_warning(
                "'%s' moved %.1f m against a median of %.1f m — check its "
                "bounding volume for a stray vertex before trusting the group"
                % (o["name"], o["delta_m"], o["median_delta_m"])
            )

    if summary["anchored"] > 2 and summary["stdev_m"] < 1.0 and abs(summary["mean_m"]) > 2.0:
        unreal.log_warning(
            "every asset moved by %.1f m +/- %.1f m. That is a datum offset, "
            "not scattered placement error — worth fixing in ion rather than "
            "re-snapping on every import."
            % (summary["mean_m"], summary["stdev_m"])
        )
    return summary


def preflight(config_path):
    """Check everything a run needs, and change nothing.

    Run this first on a new machine or a new level. It answers, in order, the
    questions that actually stop a run: is the plugin's Python surface there,
    is the level set up, is the terrain reachable, and do the manifest's
    coordinates land anywhere near the georeference. Returns True if the run
    can proceed.
    """
    checks = []

    def check(name, ok, detail="", hint=""):
        """detail is always shown; hint only when the check fails."""
        checks.append((bool(ok), name, detail if ok else (hint or detail)))
        return ok

    with open(config_path) as fh:
        cfg = json.load(fh)

    # 1. The plugin's Python surface. The sampler is the one real unknown:
    #    its factory is BlueprintInternalUseOnly, so it reaches Python only
    #    through call_method(), and nothing guarantees the binding exists.
    for name in ("Cesium3DTileset", "CesiumGeoreference", "TilesetSource"):
        check("unreal.%s" % name, hasattr(unreal, name),
              hint="is the Cesium for Unreal plugin enabled?")
    check("height sampler binding",
          getattr(unreal, "CesiumSampleHeightMostDetailedAsyncAction", None) is not None,
          hint="needs Cesium for Unreal v2.21.0+; without it the snap step "
               "cannot run at all")

    # 2. The level. Both of these are hard errors during a run.
    georef = None
    try:
        georef = require_georeference()
        origin = (georef.get_editor_property("origin_longitude"),
                  georef.get_editor_property("origin_latitude"),
                  georef.get_editor_property("origin_height"))
        check("CesiumGeoreference", True, "origin %.5f, %.5f, %.1f m" % origin)
    except RuntimeError as exc:
        check("CesiumGeoreference", False, str(exc))
        origin = None

    terrain = None
    try:
        terrain = require_terrain(cfg)
        check("terrain tileset", True, "'%s', ion asset %s"
              % (terrain.get_actor_label(), terrain.get_editor_property("ion_asset_id")))
        check("terrain streams from ion",
              terrain.get_editor_property("tileset_source")
              == unreal.TilesetSource.FROM_CESIUM_ION,
              hint="the terrain tileset's Source is not From Cesium Ion")
    except RuntimeError as exc:
        check("terrain tileset", False, str(exc))

    # 3. Credentials. Never print the token itself.
    env = cfg.get("token_env", "CESIUM_ION_TOKEN")
    check("$%s set" % env, bool(os.environ.get(env)),
          hint="export a read-only token with assets:list and assets:read")

    # 4. The manifest, and whether its coordinates are plausible.
    manifest = None
    cached = cfg.get("manifest")
    if cached and os.path.exists(cached):
        with open(cached) as fh:
            manifest = json.load(fh)
        sites = [m for m in manifest if "error" not in m]
        check("manifest", bool(sites), "%d locatable, %d failed"
              % (len(sites), len(manifest) - len(sites)))
        if sites and origin:
            ref = {"lat": origin[1], "lon": origin[0]}
            far = max(sites, key=lambda m: ground_distance_m(ref, m))
            km = ground_distance_m(ref, far) / 1000.0
            check("sites near the georeference origin", km < 100.0,
                  detail="furthest is '%s' at %.1f km" % (far["name"], km),
                  hint="furthest is '%s' at %.1f km — precision degrades this "
                       "far out; move the origin or split the level"
                       % (far["name"], km))
            extents = sum(1 for m in sites if "height_min" in m)
            check("manifest carries extents", extents == len(sites),
                  detail="%d of %d" % (extents, len(sites)),
                  hint="only %d of %d have height_min; regenerate with the "
                       "current ion_locate or they cannot cluster"
                       % (extents, len(sites)))
    else:
        check("manifest", False,
              hint="%r not found — run: py -3.13 -m cesium2unreal.ion_locate "
                   "%r > %s" % (cached, cfg.get("name_pattern", "*"),
                                cached or "manifest.json"))

    for ok, name, detail in checks:
        unreal.log("%s  %-32s %s" % ("PASS" if ok else "FAIL", name, detail))
    failed = [name for ok, name, _ in checks if not ok]
    if failed:
        unreal.log_error("preflight failed: %s" % ", ".join(failed))
    else:
        unreal.log("preflight passed — safe to run populate.run(%r)" % config_path)
    return not failed


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
        if cfg.get("cluster_models", True):
            groups = cluster_sites(sites, cfg.get("cluster_radius_m"))
        else:
            groups = [[site] for site in sites]
        clearance = float(cfg.get("seafloor_clearance_m", 0.0))
        anchor = cfg.get("depth_anchor", "bounding_volume")
        if anchor not in DEPTH_ANCHORS:
            raise RuntimeError("unknown depth_anchor %r; have %s"
                               % (anchor, sorted(DEPTH_ANCHORS)))
        lift_fn = DEPTH_ANCHORS[anchor]

        rows = []
        # Largest clusters first, so the interesting ones head the report.
        for index, members in enumerate(sorted(groups, key=lambda g: -len(g))):
            plan = plan_cluster(members, terrain, clearance, lift_fn)

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

                floor = terrain[site["id"]]
                # Where the model's own base ends up relative to the seafloor
                # beneath it: the clearance for the anchor, and for a seawall
                # the height of its base above the floor its neighbour sits on.
                base = target - (site["height"] - _deepest_point(site))
                rows.append({
                    "id": site["id"],
                    "name": site["name"],
                    "lon": site["lon"],
                    "lat": site["lat"],
                    "ion_height_m": site["height"],
                    "terrain_height_m": floor,
                    "target_height_m": target,
                    "delta_m": target - site["height"],
                    "base_above_seafloor_m": (base - floor) if floor is not None else None,
                    "placement": placement,
                    "cluster": index if len(members) > 1 else None,
                    "sampled": floor is not None,
                })

        clusters = sum(1 for g in groups if len(g) > 1)
        if clusters:
            unreal.log(
                "%d cluster(s) share one seafloor correction each; depths "
                "relative to the anchor are preserved" % clusters
            )

        report = {"summary": _summarise(rows), "assets": rows}
        if cfg.get("report"):
            with open(cfg["report"], "w") as fh:
                json.dump(report, fh, indent=2)
            moved = sum(1 for r in rows if r["placement"] != "unsampled")
        unreal.log(
            "%d of %d models corrected across %d group(s); %s"
            % (moved, len(rows), report["summary"].get("anchored", 0),
               json.dumps(report["summary"]))
        )

        unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
        unreal.log("done — level saved")

    sample_heights(terrain, positions, on_sampled,
                   timeout_s=float(cfg.get("timeout_s", 300)))
    unreal.log("sampling started; keep the editor focused until 'done' appears")
