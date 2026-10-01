#!/usr/bin/env python3
"""Audit every Cesium ion asset on the account against the dives' own nav:
is it in the right place, and is its DEPTH on the right vertical datum?

READ ONLY. Every request is a GET; it deletes nothing and changes nothing on
ion:

    GET /v1/assets?page=N&limit=100      the listing (id, name, type, status,
                                         dateAdded, bytes, description)
    GET /v1/assets/{id}                  ONLY if the listing lacked dateAdded
                                         or bytes for that asset
    GET /v1/assets/{id}/endpoint         per COMPLETE 3DTILES asset
    GET <endpoint url> (tileset.json)    with the endpoint's own access token

The ion token is read from CESIUM_ION_TOKEN (process, else the USER
environment) and goes into an Authorization header. It is never printed,
logged or written to the report; error text is scrubbed before it is kept,
and an endpoint body is never quoted (an external asset's carries a key).

Two geometries are read from each finished tileset, and each number in the
report says which one it came from:

  ROOT BOX    ``root.boundingVolume.box``. For a mesh ion tiled this is the
              tiler's padded octree root cell: a CUBE whose side is the
              mesh's largest extent and whose floor is the mesh's floor, so
              its centre sits (cube side - vertical extent) / 2 ABOVE the
              mesh's mid-height. Checked 2026-10-01 on the 92 tilesets of
              the live account that carry a tight box under a cubic root
              box: side = largest tight extent on all 92, and on the 88 in
              an East-North-Up frame the bias holds to 0.1 mm - a median
              4-7 m per dive and up to 22.7 m, most of a 25 m undulation.
              Every UNPREFIXED field (``lon``, ``lat``,
              ``height_ellipsoidal_m``, ``extent_m``, ``radius_m``,
              ``vertical_vs_cameras_m``, ``verdict`` ...) comes from it and
              is computed exactly as before, so old reports stay comparable.
  TIGHT BOX   ``root.metadata.properties.tightBoundingBox`` - the geometry's
              real box, decoded by the same code ``publish_cesium --verify``
              uses (``publish_cesium.tight_bounding_box`` / ``box_extents``).
              Every ``tight_*`` field comes from it. A tileset without the
              property (``has_tight_box`` false) gets ``tight_verdict``
              "no-tight-box" and the run carries on. Who has one, counted
              on the live account 2026-10-01 (15:00 UTC report, 419
              assets, each tileset paired with its source): 118 of the 125
              tilesets tiled from a MESH collection carry it and 0 of the
              47 tiled from a POINT-CLOUD collection do. The 7 meshes
              without it were tiled in 2023-24 (NA156), so for them, as
              for every point cloud, ``best_*`` is the root box. (This
              paragraph first said "66 of 66" and "0 of 42" as if of the
              account: those were the mesh and dense-cloud tilesets
              matched to NA165/H2060, H2063 and NA168/H2077 that morning,
              where the pattern has no exception.) A point cloud's root
              box is not a padded cube: over 40 H2060 pairs its centre sat
              a median 0.40 m (worst 6.6 m) from the same component's mesh
              tight centre.

  BEST        One column family to read: every ``best_*`` field is the
              tight box's where the tileset has one and the root box's
              where it has not (``best_geometry`` says which). So a point
              cloud is judged on its root box and a mesh on its tight box,
              and ``best_counts`` counts every dive asset once.

For each 3D Tiles asset:

  1. MODEL CENTRE - the box centre carried through ``root.transform`` (never
     the transform's translation alone: ion puts the local origin INSIDE the
     model, so origin-to-centre grows with model size and that comparison
     flagged exactly the largest H2063 components, 2026-09-23). FLOOR and
     TOP are the centre minus / plus half the box's span along true Up
     (``floor_height_ellipsoidal_m``, ``top_height_ellipsoidal_m``; of the
     three, the floor is the height ion's editor is said to show).
  2. WHICH DIVE - the nearest nav track among the flight logs given with
     ``--flight-log`` (zone-tagged: the UTM zone comes from the filename).
     Further than ``--max-km`` from every track = "unmatched".
  3. EXPECTED HEIGHT - median nav Alt of the cameras within ``--radius-m`` of
     the centre (Alt is -depth below the sea surface, an ORTHOMETRIC height)
     plus the EGM2008 undulation N there. The model sits below its cameras
     by the stand-off, so a correctly placed asset reads a few metres to
     ~15 m under this; one placed WITHOUT the geoid reads ~N metres under it
     (25 m at NA165, 66-73 m at NA168).

Verdicts (``verdict`` from the root box, ``tight_verdict`` from the tight
box, ``best_verdict`` from whichever is best - same rule): ``ok``
(horizontal within the track, vertical offset > -N/2), ``MISSING-GEOID``
(vertical offset within N/2 of -N), ``FAULT`` (anything else, or no
root.transform - raw ECEF tiles quantise to ~0.72 m). ``skipped`` (not a
finished 3D Tiles asset) and ``unreadable`` (the tileset could not be
fetched or decoded; ``why`` says how, and the run carries on) are not
verdicts on a placement.

THE CENTRE RULE MISLEADS WHERE PASSES OVERLAP. The expected height is the
median of ALL nav within the radius, not of the component's own cameras.
Replayed offline on the 2026-10-01 10:24 report (114 dive tilesets, every one
N too deep): 109 read MISSING-GEOID and 5 read FAULT - and after a correct
+N raise those same 5 would read MISSING-GEOID (H2060 zone_1_c40 mesh and
cloud, zone_1_c15, H2063 c16 and c20: each lies under the deepest of
several passes, 16-25 m below the median). No choice of radius or statistic
fixes it with nav alone (radius 5 / 10 / 30 m, the box footprint, median,
lower quartile, deepest camera: 2 to 20 wrong each). ``nav_alt_min_m`` /
``nav_alt_max_m`` / ``nav_rows_in_radius`` show the spread behind each
median. Hence the second test, on the best geometry only:

  BRACKET     ``best_bracket_verdict`` - are the cameras over the model's
              own footprint BETWEEN its floor and ``--above-top-m`` (10 m)
              above its top? Cameras are the nav rows inside the box's
              East x North span plus ``--footprint-margin-m`` (5 m); their
              median Alt plus N is compared with floor and top
              (``best_cameras_above_floor_m``, ``best_cameras_above_top_m``).
              ``ok`` = they fit with N and not without; ``MISSING-GEOID`` =
              they fit only if N is left out (the model is N too deep);
              ``ambiguous`` = both fit (a box taller than about N - 10 m
              cannot tell); ``FAULT`` = neither; ``no-nav`` = no nav row
              over the footprint; ``not-assessed`` = unmatched, or no
              transform or extents. On the same replay: now 109
              MISSING-GEOID, 4 ambiguous, 1 FAULT; after +N 108 ok,
              5 ambiguous, 1 FAULT (zone_1_c35_L_dense both times: the
              cameras over it are 10.4 m above its top) - no asset is
              called ok while N too deep, or MISSING-GEOID once raised,
              and the five the centre rule gets wrong read correctly. It
              works on walls, where the centre is tens of metres from any
              camera; it cannot decide a box taller than about N - 10 m.

Other limits - read a verdict with them in mind:

  - the thresholds of the centre rule assume N > 0 (true at every site
    audited so far);
  - ``tight_extent_m`` is E x N x U only where the tileset's local frame is
    East-North-Up: ``local_axes_off_enu_deg`` says how far it is from that,
    and ``tight_extent_enu_m`` / ``extent_enu_m`` are the boxes' spans along
    true E / N / U. Even then the box is aligned to the axes the GEOMETRY
    was supplied in: the H2060 meshes were uploaded in UTM grid axes, which
    at that site are 0.48 deg off true East / North, in a frame ion labels
    East-North-Up. The audit cannot see that; it is a limit, not a fault;
  - ``bytes`` on a tileset row is the TILED size. The uploaded size is on
    the source collection, which ion's listing does not link: the report
    pairs them (``source_asset_id``, ``source_bytes``, ``source_pairing``)
    by "the asset one id below with the same name", else by a name only one
    collection carries - a heuristic, stated per row, never a guess where
    two collections share a name.

Per asset the report also carries ``date_added`` (UTC, as ion gives it),
``bytes`` and, when ion has one, ``description`` - for every asset, the
skipped source collections included. ``generated`` is UTC too.
``--compare <previous report>`` adds a ``changes`` block - assets gone, new
and changed since that report (either schema) - and prints it.

The report states its own conventions (``conventions``): which heights are
ellipsoidal and which orthometric, the sign of N and of every difference.
It is strict JSON - a tileset whose centre or extents are not finite is an
"unreadable" row, never a NaN in the file - and it is on disk BEFORE the
``--compare`` listing is printed; the compare file's shape and the ``--out``
folder are checked before the first request.

Needs requests, pyproj and numpy, and the EGM2008 grid locally or PROJ
network access; without the grid PROJ would silently return N = 0, so the
transform is built with allow_ballpark=False and fails instead, and a
non-finite N stops the run.

Usage:
    python validate_cesium_assets.py --flight-log <log> [--flight-log <log>...]
        [--out report.json] [--compare previous_report.json]
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from publish_cesium import box_extents, tight_bounding_box  # noqa: E402

API = "https://api.cesium.com"

#: Report layout. 1 = the 2026-09-30 report (root box only); 2 added the
#: listing fields, the box half-axes and the tight-box centre and verdict;
#: 3 adds floor and top heights, the ``best_*`` family, the bracket test,
#: the source pairing, ``generated`` in UTC and ``changes``. Every schema-1
#: and schema-2 field is still written, with the same meaning. Still 3 with
#: the top-level ``conventions`` block (and ``changes_error`` /
#: ``non_finite_values_nulled`` when they apply): the rows did not change.
SCHEMA = 3

ROOT_BOX = "root.boundingVolume.box"
TIGHT_BOX = "root.metadata.properties.tightBoundingBox"

#: The bracket test: how far above a model's top its cameras may sit.
CAMERAS_ABOVE_TOP_M = 10.0
#: The bracket test: how far outside the box's footprint a camera may be.
FOOTPRINT_MARGIN_M = 5.0

#: Which geometry each report field was computed from.
FIELDS = {
    "date_added / bytes / description": "the ion asset listing (not "
                                        "geometry); bytes on a tileset is "
                                        "the tiled size, date_added is UTC",
    "source_asset_id / source_type / source_bytes / source_pairing / "
    "tileset_asset_id": "the listing: the source collection a tileset was "
                        "tiled from, paired by id and name (a heuristic - "
                        "ion does not link them; source_pairing says how)",
    "extent_m / radius_m / root_box_centre_local_m / root_box_half_axes_m":
        ROOT_BOX + " - ion's padded octree root cell, a cube",
    "extent_enu_m": ROOT_BOX + " half-axes through root.transform, span "
                    "along true East / North / Up",
    "lon / lat / height_ellipsoidal_m": ROOT_BOX + " centre through "
                                        "root.transform",
    "floor_height_ellipsoidal_m / top_height_ellipsoidal_m":
        ROOT_BOX + " centre height minus / plus half its span along Up",
    "dive_log / distance_to_track_m / geoid_n_m / nav_* / expected_height_m "
    "/ vertical_vs_cameras_m / verdict / why":
        "nav and geoid at the " + ROOT_BOX + " centre",
    "tight_box_centre_local_m / tight_box_half_axes_m / tight_extent_m":
        TIGHT_BOX + " (publish_cesium.tight_bounding_box / box_extents); "
                    "E x N x U only in an East-North-Up frame, and then "
                    "along the axes the geometry was supplied in",
    "tight_extent_enu_m": TIGHT_BOX + " half-axes through root.transform, "
                          "span along true East / North / Up",
    "tight_lon / tight_lat / tight_height_ellipsoidal_m":
        TIGHT_BOX + " centre through root.transform",
    "tight_floor_height_ellipsoidal_m / tight_top_height_ellipsoidal_m":
        TIGHT_BOX + " centre height minus / plus half its span along Up",
    "tight_dive_log / tight_distance_to_track_m / tight_geoid_n_m / "
    "tight_nav_* / tight_expected_height_m / tight_vertical_vs_cameras_m / "
    "tight_verdict / tight_why": "nav and geoid at the " + TIGHT_BOX
                                 + " centre",
    "root_centre_above_tight_centre_m": "height_ellipsoidal_m minus "
                                        "tight_height_ellipsoidal_m",
    "best_geometry": "which box every best_* field is from: " + TIGHT_BOX
                     + " where the tileset has one, else " + ROOT_BOX,
    "best_lon / best_lat / best_height_ellipsoidal_m / best_floor_* / "
    "best_top_* / best_extent_enu_m / best_dive_log / best_geoid_n_m / "
    "best_nav_* / best_expected_height_m / best_vertical_vs_cameras_m / "
    "best_verdict / best_why": "copies of the tight_* fields, or of the "
                               "unprefixed root-box fields (best_geometry)",
    "best_footprint_nav_* / best_cameras_above_floor_m / "
    "best_cameras_above_top_m / best_bracket_verdict / best_bracket_why":
        "the bracket test: nav rows over the best box's East x North "
        "footprint (+ margin), their median Alt + N against its floor and "
        "top",
    "local_axes_scale / local_axes_off_enu_deg":
        "root.transform's own axes against East-North-Up at its origin",
}

#: Signs and vertical datums of the report's numbers. Written into every
#: report: the module docstring does not travel with the JSON.
CONVENTIONS = {
    "heights": "every *_height_ellipsoidal_m (and expected_height_m) is "
               "metres above the WGS84 ELLIPSOID, positive up - the datum "
               "Cesium ion places an asset on",
    "nav_alt": "every nav_alt_* and footprint_nav_alt_* is the flight log's "
               "Alt: an ORTHOMETRIC height, minus the depth below the sea "
               "surface, in metres (negative under water). It is not "
               "ellipsoidal",
    "geoid_n_m": "the EGM2008 undulation N in metres, positive where the "
                 "geoid is ABOVE the ellipsoid; ellipsoidal h = orthometric "
                 "H + N, so expected_height_m = nav_alt_median_m + geoid_n_m",
    "vertical_vs_cameras_m": "asset height minus expected height "
                             "(height_ellipsoidal_m - expected_height_m). "
                             "Negative = the model is BELOW its cameras; an "
                             "asset placed without the geoid reads about N "
                             "more negative than a correct one",
    "cameras_above_floor_m / cameras_above_top_m": "footprint nav median + "
                                                   "N, minus the box's floor "
                                                   "/ top height. Positive = "
                                                   "the cameras are above it",
    "root_centre_above_tight_centre_m": "positive = the root box centre is "
                                        "higher than the tight box centre",
    "extents": "metres; *_extent_enu_m is East x North x Up, extent_m and "
               "tight_extent_m follow the box's own axes",
    "lon / lat": "degrees, WGS84, east and north positive",
}

_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")


class Unreadable(Exception):
    """A tileset that cannot be audited, with a reason worth reading."""


def token() -> str:
    from publish_cesium import ion_token_from_environment
    tok = ion_token_from_environment()
    if not tok:
        raise SystemExit("no CESIUM_ION_TOKEN available")
    return tok


def scrub(text: str, secrets=()) -> str:
    """``text`` with every secret - and anything shaped like an ion token -
    replaced, so an exception message can be kept without leaking one."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "<redacted>")
    return _JWT.sub("<redacted>", text)


def explain(exc: BaseException, secrets=()) -> str:
    """Why a tileset was unreadable: scrubbed first, then cut to length.

    A bare ``str(KeyError('url'))`` is "'url'", which says nothing, so
    anything that is not already an :class:`Unreadable` carries its type.
    """
    text = str(exc)
    if not isinstance(exc, Unreadable):
        text = "%s: %s" % (type(exc).__name__, text)
    return scrub(text, secrets)[:160]


# --------------------------------------------------------------------------
# ion - GET only
# --------------------------------------------------------------------------

def list_assets(session, tok: str) -> list[dict]:
    out, page = [], 1
    while True:
        r = session.get("%s/v1/assets" % API,
                        headers={"Authorization": "Bearer " + tok},
                        params={"page": page, "limit": 100}, timeout=60)
        r.raise_for_status()
        items = r.json().get("items") or []
        if not items:
            break
        out.extend(items)
        if len(items) < 100:
            break
        page += 1
    return out


def asset_detail(session, tok: str, asset_id: int) -> dict:
    """GET /v1/assets/{id} - asked only when the listing lacks a field."""
    r = session.get("%s/v1/assets/%d" % (API, asset_id),
                    headers={"Authorization": "Bearer " + tok}, timeout=60)
    r.raise_for_status()
    return r.json()


def fetch_tileset(session, tok: str, asset_id: int) -> dict:
    """The asset's tileset.json, through its endpoint.

    Both GETs are checked: an HTTP error whose body happens to be JSON must
    not be decoded as a tileset (it would read "FAULT, no root.transform").
    An asset ion only points at (Google Photorealistic 3D Tiles) has an
    endpoint with no ``url`` / ``accessToken`` of ion's own; its body holds
    the third party's key, so only its ``externalType`` is ever quoted.
    """
    h = {"Authorization": "Bearer " + tok}
    e = session.get("%s/v1/assets/%d/endpoint" % (API, asset_id),
                    headers=h, timeout=60)
    e.raise_for_status()
    ep = e.json()
    if not isinstance(ep, dict) or not ep.get("url") or not ep.get("accessToken"):
        kind = ep.get("externalType") if isinstance(ep, dict) else None
        if kind:
            raise Unreadable("external asset (externalType %s): ion hosts no "
                             "tileset for it" % str(kind)[:40])
        raise Unreadable("the endpoint carries no tileset url and access "
                         "token")
    # The endpoint's own access token is a secret too, and only this
    # function ever holds it: a failure is scrubbed of BOTH tokens here,
    # before it can travel anywhere. (ion's are JWT-shaped, which scrub()
    # removes anyway; a token of another shape would have reached ``why``.)
    try:
        r = session.get(
            ep["url"],
            headers={"Authorization": "Bearer " + ep["accessToken"]},
            timeout=120)
        r.raise_for_status()
        return r.json()
    except Exception as exc:                                   # noqa: BLE001
        raise Unreadable(
            explain(exc, (tok, str(ep["accessToken"])))) from None


def asset_fields(item: dict) -> dict:
    """The listing half of a report row. ``description`` only if ion has one."""
    rec = {"asset_id": item.get("id"), "name": item.get("name"),
           "type": item.get("type"), "status": item.get("status"),
           "date_added": item.get("dateAdded"), "bytes": item.get("bytes")}
    if item.get("description"):
        rec["description"] = item["description"]
    return rec


# --------------------------------------------------------------------------
# tileset.json - offline decoding
# --------------------------------------------------------------------------

def carry(m, x: float, y: float, z: float) -> tuple:
    """A local point through a column-major 4x4 ``root.transform`` -> ECEF."""
    return (m[0] * x + m[4] * y + m[8] * z + m[12],
            m[1] * x + m[5] * y + m[9] * z + m[13],
            m[2] * x + m[6] * y + m[10] * z + m[14])


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def tight_box(tileset: dict):
    """(twelve floats, "") for the tight box, or (None, why it is absent).

    The lookup itself is publish_cesium's; this only refuses what cannot be
    decoded, so a tileset without the property - or with a null where an
    object should be - is a recorded absence rather than a crash.
    """
    try:
        raw = tight_bounding_box(tileset)
    except (AttributeError, TypeError):
        return None, "root.metadata is not an object"
    if raw is None:
        return None, "no " + TIGHT_BOX
    if not isinstance(raw, (list, tuple)) or len(raw) < 12:
        return None, "tightBoundingBox is not twelve numbers"
    if not all(_is_number(v) for v in raw[:12]):
        return None, "tightBoundingBox is not numeric"
    values = [float(v) for v in raw[:12]]
    if not all(math.isfinite(v) for v in values):
        return None, "tightBoundingBox holds a non-finite value"
    return values, ""


def _all_finite(values) -> bool:
    """True when every number in a (possibly nested) list is finite."""
    if isinstance(values, (list, tuple)):
        return all(_all_finite(v) for v in values)
    return math.isfinite(values)


def decode_tileset(tileset: dict) -> dict:
    """Everything the audit takes from a tileset.json. No network, no PROJ.

    ``extent_m``, ``radius_m``, ``has_root_transform`` and ``centre_ecef``
    are the 2026-09-30 audit's own numbers, computed the same way. A body
    that is not a tileset raises; the caller records it as "unreadable".
    So does one whose centre or extents come out non-finite (a NaN in the
    transform, a box whose half-axes overflow): a row of NaN verdicts is
    not an audit, and NaN / Infinity are not JSON.
    """
    if not isinstance(tileset, dict):
        raise Unreadable("the tileset body is a %s, not a JSON object"
                         % type(tileset).__name__)
    root = tileset.get("root") or {}
    m = root.get("transform")
    box = (root.get("boundingVolume") or {}).get("box")
    out: dict = {"extent_m": None, "radius_m": None, "transform": None,
                 "has_root_transform": bool(m) and len(m) >= 16,
                 "centre_ecef": None, "has_root_box_centre": False}
    if box and len(box) >= 12:
        hx, hy, hz = box[3:6], box[6:9], box[9:12]
        out["extent_m"] = [2 * math.sqrt(sum(c * c for c in v))
                           for v in (hx, hy, hz)]
        try:
            out["radius_m"] = math.sqrt(
                sum((a + b + c) ** 2 for a, b, c in zip(hx, hy, hz)))
        except OverflowError:               # ** raises where * returns inf
            raise Unreadable(ROOT_BOX + " radius is not finite") from None
        out["root_box_centre_local_m"] = [float(c) for c in box[0:3]]
        out["root_box_half_axes_m"] = [[float(c) for c in v]
                                       for v in (hx, hy, hz)]

    tight, why = tight_box(tileset)
    out["has_tight_box"] = tight is not None
    if tight is None:
        out["tight_box_absent_why"] = why
    else:
        out["tight_box_centre_local_m"] = tight[0:3]
        out["tight_box_half_axes_m"] = [tight[3:6], tight[6:9], tight[9:12]]
        out["tight_extent_m"] = box_extents(tight)

    if out["has_root_transform"]:
        out["transform"] = [float(v) for v in m[:16]]
        out["has_root_box_centre"] = bool(box) and len(box) >= 3
        cx, cy, cz = ((box[0], box[1], box[2]) if out["has_root_box_centre"]
                      else (0.0, 0.0, 0.0))
        out["centre_ecef"] = tuple(float(v) for v in carry(m, cx, cy, cz))
        if tight is not None:
            out["tight_centre_ecef"] = tuple(
                float(v) for v in carry(m, *tight[0:3]))
    for key, what in (("transform", "root.transform"),
                      ("extent_m", ROOT_BOX + " extents"),
                      ("radius_m", ROOT_BOX + " radius"),
                      ("root_box_centre_local_m", ROOT_BOX + " centre"),
                      ("centre_ecef", "the root box centre in ECEF"),
                      ("tight_extent_m", TIGHT_BOX + " extents"),
                      ("tight_centre_ecef", "the tight box centre in ECEF")):
        if out.get(key) is not None and not _all_finite(out[key]):
            raise Unreadable("%s is not finite" % what)
    return out


def local_frame(m, to_geo) -> dict:
    """How far the tileset's local axes are from East-North-Up at its origin.

    The columns of root.transform's upper 3x3 are the local X, Y, Z axes in
    ECEF. ion builds an East-North-Up frame for a mesh uploaded with
    ``options.position``; anything else means ``tight_extent_m`` is NOT
    E x N x U, which is why this is recorded instead of assumed.
    """
    from modules.cesium_placement import ecef_enu_rotation

    cols = [(m[0], m[1], m[2]), (m[4], m[5], m[6]), (m[8], m[9], m[10])]
    scale = [math.sqrt(sum(c * c for c in col)) for col in cols]
    origin = (m[12], m[13], m[14])
    out = {"local_axes_scale": scale, "local_axes_off_enu_deg": None}
    # An origin nowhere near the Earth's surface has no East-North-Up.
    if math.sqrt(sum(c * c for c in origin)) < 6.0e6 or min(scale) <= 0.0:
        return out
    lon, lat, _h = to_geo.transform(*origin)
    if not (math.isfinite(lon) and math.isfinite(lat)):
        return out
    enu = ecef_enu_rotation(lon, lat)
    worst = 0.0
    for col, length, row in zip(cols, scale, enu):
        cosine = sum(a * float(b) for a, b in zip(col, row)) / length
        worst = max(worst,
                    math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))
    out["local_axes_off_enu_deg"] = worst
    return out


def enu_span(m, half_axes, lon: float, lat: float) -> list[float]:
    """Span of an oriented box along true East, North and Up, in metres.

    Equal to the box's own edge lengths when its axes are East-North-Up;
    larger (it is the enclosing axis-aligned span) when they are not.
    """
    from modules.cesium_placement import ecef_enu_rotation

    enu = ecef_enu_rotation(lon, lat)
    span = [0.0, 0.0, 0.0]
    for v in half_axes:
        ecef = (m[0] * v[0] + m[4] * v[1] + m[8] * v[2],
                m[1] * v[0] + m[5] * v[1] + m[9] * v[2],
                m[2] * v[0] + m[6] * v[1] + m[10] * v[2])
        for k in range(3):
            span[k] += abs(sum(float(enu[k][j]) * ecef[j] for j in range(3)))
    return [2.0 * s for s in span]


# --------------------------------------------------------------------------
# nav
# --------------------------------------------------------------------------

def utm_epsg(path: str) -> str:
    """EPSG code from a zone-tagged flight-log name (..._2L_UTM, _53N_UTM)."""
    m = re.search(r"_(\d{1,2})([C-X])_UTM", os.path.basename(path), re.IGNORECASE)
    if not m:
        raise SystemExit("no UTM zone tag in %s" % path)
    zone, band = int(m.group(1)), m.group(2).upper()
    return "EPSG:%d" % ((32600 if band >= "N" else 32700) + zone)


def load_nav(path: str) -> list[tuple]:
    rows = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        next(fh)
        for line in fh:
            p = line.split(";")
            try:
                rows.append((float(p[1]), float(p[2]), float(p[3])))
            except (ValueError, IndexError):
                continue
    return rows


def geoid_lookup():
    """N(lon, lat) in metres from EGM2008 - an error, never a silent zero.

    ``allow_ballpark=False`` makes a missing grid raise at construction. A
    grid that is missing while PROJ network is on and the CDN is unreachable
    comes back as ``inf`` instead (BUGS.md B26); auditing against that would
    make every verdict garbage, so it stops the run.
    """
    from pyproj import Transformer

    geoid = Transformer.from_crs("EPSG:9518", "EPSG:4979", always_xy=True,
                                 allow_ballpark=False)

    def lookup(lon: float, lat: float) -> float:
        n = geoid.transform(lon, lat, 0.0)[2]
        if not math.isfinite(n):
            raise SystemExit(
                "the EGM2008 undulation came back %r at lon=%.5f lat=%.5f - "
                "the geoid grid is not usable (missing, and not fetchable). "
                "Refusing to audit against it." % (n, lon, lat))
        return float(n)

    return lookup


def classify(dv: float, n: float) -> tuple:
    """(verdict, why) for a vertical offset ``dv`` against the cameras."""
    if abs(dv + n) <= n / 2:
        return "MISSING-GEOID", ("%.1f m under the cameras = the %.1f m "
                                 "undulation" % (-dv, n))
    if dv > -n / 2 and dv < 10:
        return "ok", None
    return "FAULT", "vertical %+.1f m vs cameras (N %.1f)" % (dv, n)


def nearest_track(navs: list, lon: float, lat: float) -> dict:
    """The dive whose nav passes closest to a point, and the point in that
    dive's grid: ``distance_m``, ``nav``, ``east``, ``north`` and ``d2`` (a
    squared distance and an Alt per nav row)."""
    best = None
    for nv in navs:
        e, n = nv["fwd"].transform(lon, lat)
        d2 = [((x - e) ** 2 + (y - n) ** 2, z) for x, y, z in nv["rows"]]
        dmin = math.sqrt(min(d for d, _z in d2))
        if best is None or dmin < best["distance_m"]:
            best = {"distance_m": dmin, "nav": nv, "east": e, "north": n,
                    "d2": d2}
    return best


def assess(track: dict, geoid_n, lon: float, lat: float, h: float,
           radius_m: float, max_km: float) -> dict:
    """Dive match, expected height and verdict for ONE centre.

    Keys are unprefixed; the caller stores them as they are for the root
    box and under ``tight_`` for the tight box. ``geoid_n_m`` is recorded
    for every centre matched to a dive, also one with no camera in the
    radius, so a table of N needs nothing recomputed.
    """
    dmin = track["distance_m"]
    near = [z for d, z in track["d2"] if d <= radius_m ** 2]
    out = {"dive_log": os.path.basename(track["nav"]["log"]),
           "distance_to_track_m": dmin}
    if dmin > max_km * 1000:
        out["verdict"] = "unmatched"
        out["why"] = "%.1f km from every nav track" % (dmin / 1000)
        return out
    undulation = None
    if math.isfinite(lon) and math.isfinite(lat):
        undulation = out["geoid_n_m"] = geoid_n(lon, lat)
    if not near or undulation is None:
        out["verdict"], out["why"] = "FAULT", "%.0f m from the nav track" % dmin
        return out
    median = statistics.median(near)
    expected = median + undulation
    dv = h - expected
    out.update(nav_alt_median_m=median,
               expected_height_m=expected, vertical_vs_cameras_m=dv,
               nav_rows_in_radius=len(near), nav_alt_min_m=min(near),
               nav_alt_max_m=max(near))
    verdict, why = classify(dv, undulation)
    out["verdict"] = verdict
    if why:
        out["why"] = why
    return out


def bracket(track: dict, undulation: float, floor: float, top: float,
            half_east: float, half_north: float,
            margin_m: float = FOOTPRINT_MARGIN_M,
            above_top_m: float = CAMERAS_ABOVE_TOP_M) -> dict:
    """Are the cameras over a box's footprint between its floor and top?

    The cameras are the nav rows inside the box's East x North span plus
    ``margin_m``; their median Alt (orthometric) plus N is where they are
    on the ellipsoid. A model on the right datum has them above its floor
    and no more than ``above_top_m`` above its top. One that is N too deep
    has them there only when N is left out. Keys are unprefixed.
    """
    e, n = track["east"], track["north"]
    he, hn = half_east + margin_m, half_north + margin_m
    alts = [z for x, y, z in track["nav"]["rows"]
            if abs(x - e) <= he and abs(y - n) <= hn]
    out: dict = {"footprint_nav_rows": len(alts)}
    if not alts:
        out["bracket_verdict"] = "no-nav"
        out["bracket_why"] = ("no nav row over the box footprint (+%g m)"
                              % margin_m)
        return out
    median = statistics.median(alts)
    cameras = median + undulation
    out.update(footprint_nav_alt_median_m=median,
               footprint_nav_alt_min_m=min(alts),
               footprint_nav_alt_max_m=max(alts),
               cameras_above_floor_m=cameras - floor,
               cameras_above_top_m=cameras - top)
    with_n = floor < cameras <= top + above_top_m
    without_n = floor < median <= top + above_top_m
    if with_n and without_n:
        out["bracket_verdict"] = "ambiguous"
        out["bracket_why"] = ("the cameras fit with N and without it (box "
                              "%.1f m tall, N %.1f)" % (top - floor, undulation))
    elif with_n:
        out["bracket_verdict"] = "ok"
    elif without_n:
        out["bracket_verdict"] = "MISSING-GEOID"
        out["bracket_why"] = ("the cameras are %+.1f m from the top with N "
                              "and %+.1f m without it: the model is N too "
                              "deep" % (cameras - top, median - top))
    else:
        out["bracket_verdict"] = "FAULT"
        out["bracket_why"] = ("the cameras are %+.1f m from the top and "
                              "%+.1f m from the floor (N %.1f)"
                              % (cameras - top, cameras - floor, undulation))
    return out


# --------------------------------------------------------------------------
# the audit
# --------------------------------------------------------------------------

_GEOMETRY_KEYS = ("root_box_centre_local_m", "root_box_half_axes_m",
                  "has_tight_box", "tight_box_absent_why",
                  "tight_box_centre_local_m", "tight_box_half_axes_m",
                  "tight_extent_m")

#: Copied to ``best_<key>`` from the tight box's fields, else the root box's.
_BEST_KEYS = ("lon", "lat", "height_ellipsoidal_m",
              "floor_height_ellipsoidal_m", "top_height_ellipsoidal_m",
              "extent_enu_m", "dive_log", "distance_to_track_m", "geoid_n_m",
              "nav_alt_median_m", "nav_alt_min_m", "nav_alt_max_m",
              "nav_rows_in_radius", "expected_height_m",
              "vertical_vs_cameras_m", "verdict", "why")


def _floor_and_top(h: float, span: list) -> dict:
    return {"extent_enu_m": span,
            "floor_height_ellipsoidal_m": h - span[2] / 2.0,
            "top_height_ellipsoidal_m": h + span[2] / 2.0}


def audit_tileset(rec: dict, tileset: dict, navs: list, geoid_n, to_geo,
                  radius_m: float, max_km: float,
                  margin_m: float = FOOTPRINT_MARGIN_M,
                  above_top_m: float = CAMERAS_ABOVE_TOP_M) -> dict:
    """Fill one report row from a tileset.json. Returns ``rec``."""
    geo = decode_tileset(tileset)
    rec.update(extent_m=geo["extent_m"], radius_m=geo["radius_m"],
               has_root_transform=geo["has_root_transform"])
    for key in _GEOMETRY_KEYS:
        if key in geo:
            rec[key] = geo[key]
    has_tight = geo["has_tight_box"]
    best = "tight_" if has_tight else ""
    rec["verdict_geometry"] = ROOT_BOX + " centre"
    rec["tight_verdict_geometry"] = (TIGHT_BOX + " centre") if has_tight else None
    rec["best_geometry"] = TIGHT_BOX if has_tight else ROOT_BOX

    if not geo["has_root_transform"]:
        why = "no root.transform - raw ECEF tiles (float32, ~0.72 m)"
        rec["verdict"], rec["why"] = "FAULT", why
        if has_tight:
            rec["tight_verdict"], rec["tight_why"] = "FAULT", why
        else:
            rec["tight_verdict"] = "no-tight-box"
            rec["tight_why"] = geo["tight_box_absent_why"]
        rec["best_verdict"], rec["best_why"] = "FAULT", why
        rec["best_bracket_verdict"] = "not-assessed"
        rec["best_bracket_why"] = why
        return rec

    m = geo["transform"]
    if not geo["has_root_box_centre"]:
        rec["verdict_geometry"] = "root.transform origin (no root box)"
        if not has_tight:
            rec["best_geometry"] = rec["verdict_geometry"]
    rec.update(local_frame(m, to_geo))
    lon, lat, h = to_geo.transform(*geo["centre_ecef"])
    if not _all_finite([lon, lat, h]):
        raise Unreadable("the root box centre does not convert to lon / lat "
                         "/ height")
    rec.update(lon=lon, lat=lat, height_ellipsoidal_m=h)
    if "root_box_half_axes_m" in geo:
        rec.update(_floor_and_top(
            h, enu_span(m, geo["root_box_half_axes_m"], lon, lat)))
    track = nearest_track(navs, lon, lat)
    rec.update(assess(track, geoid_n, lon, lat, h, radius_m, max_km))

    if has_tight:
        tlon, tlat, th = to_geo.transform(*geo["tight_centre_ecef"])
        if not _all_finite([tlon, tlat, th]):
            raise Unreadable("the tight box centre does not convert to lon "
                             "/ lat / height")
        rec.update(tight_lon=tlon, tight_lat=tlat,
                   tight_height_ellipsoidal_m=th,
                   root_centre_above_tight_centre_m=h - th)
        for key, value in _floor_and_top(
                th, enu_span(m, geo["tight_box_half_axes_m"],
                             tlon, tlat)).items():
            rec["tight_" + key] = value
        track = nearest_track(navs, tlon, tlat)
        for key, value in assess(track, geoid_n, tlon, tlat, th,
                                 radius_m, max_km).items():
            rec["tight_" + key] = value
    else:
        rec["tight_verdict"] = "no-tight-box"
        rec["tight_why"] = geo["tight_box_absent_why"]

    for key in _BEST_KEYS:
        if best + key in rec:
            rec["best_" + key] = rec[best + key]
    span, undulation = rec.get("best_extent_enu_m"), rec.get("best_geoid_n_m")
    if span is None or undulation is None:
        result = {"bracket_verdict": "not-assessed",
                  "bracket_why": (rec.get("best_why") if undulation is None
                                  else "no box extents")}
    else:
        result = bracket(track, undulation,
                         rec["best_floor_height_ellipsoidal_m"],
                         rec["best_top_height_ellipsoidal_m"],
                         span[0] / 2.0, span[1] / 2.0, margin_m, above_top_m)
    for key, value in result.items():
        rec["best_" + key] = value
    return rec


def audit_assets(assets: list, fetch, navs: list, geoid_n, to_geo,
                 radius_m: float, max_km: float, secrets=(),
                 margin_m: float = FOOTPRINT_MARGIN_M,
                 above_top_m: float = CAMERAS_ABOVE_TOP_M) -> list[dict]:
    """One report row per asset. ``fetch(asset_id)`` returns a tileset.json.

    A tileset that cannot be fetched OR decoded is one "unreadable" row and
    the audit goes on to the next asset: the report is only written at the
    end, so one bad body must not cost the run. (A non-finite geoid is a
    SystemExit, not an Exception: that one does stop it.)
    """
    rows = []
    for a in sorted(assets, key=lambda x: x.get("id", 0)):
        rec = asset_fields(a)
        rows.append(rec)
        if a.get("type") != "3DTILES" or a.get("status") != "COMPLETE":
            for key in ("verdict", "tight_verdict", "best_verdict",
                        "best_bracket_verdict"):
                rec[key] = "skipped"
            rec["why"] = "%s/%s" % (a.get("type"), a.get("status"))
            continue
        try:
            row = audit_tileset({}, fetch(a["id"]), navs, geoid_n, to_geo,
                                radius_m, max_km, margin_m, above_top_m)
        except Exception as exc:                               # noqa: BLE001
            for key in ("verdict", "tight_verdict", "best_verdict",
                        "best_bracket_verdict"):
                rec[key] = "unreadable"
            rec["why"] = explain(exc, secrets)
            continue
        rec.update(row)
    pair_sources(rows)
    return rows


def pair_sources(rows: list) -> list:
    """Link each tileset to the source collection it was tiled from.

    ion's listing has no such link. An upload creates the source collection
    and the tileset together, one id apart and under one name - 115 of the
    live account's 156 tilesets pair that way (2026-10-01, added within
    0.08 s of each other); older sources were migrated to collections with
    new ids, so the fallback is a name carried by exactly one collection
    and one other asset. Every 3DTILES row gets ``source_asset_id`` (None
    when no source is left) and ``source_pairing``; the paired source row
    gets ``tileset_asset_id``.
    """
    def is_collection(r):
        return str(r.get("type") or "").endswith("_COLLECTION")

    by_id = {r.get("asset_id"): r for r in rows if r.get("asset_id") is not None}
    by_name: dict = {}
    for r in rows:
        by_name.setdefault(r.get("name"), []).append(r)
    for r in rows:
        if is_collection(r):
            continue
        source, how = None, None
        below = by_id.get(r["asset_id"] - 1) if _is_number(r.get("asset_id")) else None
        if (below is not None and is_collection(below)
                and below.get("name") == r.get("name")):
            source, how = below, "the asset one id below, same name"
        else:
            same = by_name.get(r.get("name"), [])
            sources = [s for s in same if is_collection(s)]
            if len(sources) == 1 and len(same) == 2:
                source, how = sources[0], "the only collection of that name"
            elif len(sources) > 1 or (sources and len(same) > 2):
                how = ("not paired: %d assets share the name, %d of them "
                       "collections" % (len(same), len(sources)))
        if source is not None:
            r.update(source_asset_id=source.get("asset_id"),
                     source_type=source.get("type"),
                     source_bytes=source.get("bytes"), source_pairing=how)
            source["tileset_asset_id"] = r.get("asset_id")
        elif r.get("type") == "3DTILES":
            r.update(source_asset_id=None,
                     source_pairing=how or "no source collection left")
    return rows


# --------------------------------------------------------------------------
# against a previous report
# --------------------------------------------------------------------------

#: What makes an asset "changed" between two reports, and how close a
#: number has to be to count as the same.
_COMPARED = {"name": None, "type": None, "status": None, "bytes": None,
             "description": None, "has_root_transform": None,
             "verdict": None, "tight_verdict": None, "best_verdict": None,
             "best_bracket_verdict": None,
             "lon": 1e-8, "lat": 1e-8, "height_ellipsoidal_m": 1e-3,
             "tight_lon": 1e-8, "tight_lat": 1e-8,
             "tight_height_ellipsoidal_m": 1e-3}


def _brief(row: dict) -> dict:
    return {key: row[key] for key in ("asset_id", "name", "type", "status",
                                      "date_added", "bytes") if key in row}


def _same(a, b, tolerance) -> bool:
    if tolerance is not None and _is_number(a) and _is_number(b):
        return abs(a - b) <= tolerance
    return a == b


def compare_reports(previous: dict, rows: list) -> dict:
    """What changed on the account since ``previous`` (a saved report).

    ``gone`` and ``new`` are assets by id; ``changed`` lists, per asset in
    both, the compared fields that differ. A field the previous report never
    wrote (an older schema) is not a change.
    """
    def in_order(ids):
        return sorted(ids, key=lambda i: (not _is_number(i), i if _is_number(i) else str(i)))

    before = {r.get("asset_id"): r for r in previous.get("assets") or []}
    now = {r.get("asset_id"): r for r in rows}
    known = set()
    for r in before.values():
        known.update(r)
    changed = []
    for asset_id in in_order(set(before) & set(now)):
        was, cur = {}, {}
        for key, tolerance in _COMPARED.items():
            if key not in known:
                continue
            a, b = before[asset_id].get(key), now[asset_id].get(key)
            if not _same(a, b, tolerance):
                was[key], cur[key] = a, b
        if was:
            changed.append({"asset_id": asset_id,
                            "name": now[asset_id].get("name"),
                            "was": was, "now": cur})
    return {
        "previous_generated": previous.get("generated"),
        "previous_schema": previous.get("schema", 1),
        "previous_assets": len(before), "assets": len(now),
        "gone": [_brief(before[i]) for i in in_order(set(before) - set(now))],
        "new": [_brief(now[i]) for i in in_order(set(now) - set(before))],
        "changed": changed,
    }


def check_previous_report(previous, path: str) -> None:
    """Refuse a ``--compare`` file :func:`compare_reports` could not read.

    Called before the first request. The old check was "a dict with an
    ``assets`` key"; ``{"assets": [1, 2]}`` passed it and then crashed the
    comparison AFTER the whole audit and BEFORE the report was written.
    """
    if not isinstance(previous, dict) or "assets" not in previous:
        raise SystemExit("%s is not an audit report" % path)
    rows = previous["assets"]
    if not isinstance(rows, list):
        raise SystemExit('%s is not an audit report: "assets" is a %s, not '
                         'a list' % (path, type(rows).__name__))
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise SystemExit("%s is not an audit report: assets[%d] is a "
                             "%s, not an object"
                             % (path, index, type(row).__name__))
        if isinstance(row.get("asset_id"), (list, dict)):
            raise SystemExit("%s is not an audit report: assets[%d] has a "
                             "%s for its asset_id" % (
                                 path, index,
                                 type(row["asset_id"]).__name__))


def check_out_path(path: str) -> None:
    """Refuse an ``--out`` that cannot be written, before the first request
    rather than after the last."""
    folder = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(folder):
        raise SystemExit("--out: the folder %s does not exist" % folder)
    if os.path.isdir(path):
        raise SystemExit("--out: %s is a folder, not a file" % path)


def _nulled(value):
    """(value with every non-finite float replaced by None, how many)."""
    if isinstance(value, float) and not math.isfinite(value):
        return None, 1
    if isinstance(value, dict):
        out, total = {}, 0
        for key, item in value.items():
            out[key], count = _nulled(item)
            total += count
        return out, total
    if isinstance(value, (list, tuple)):
        pairs = [_nulled(item) for item in value]
        return [item for item, _count in pairs], sum(c for _i, c in pairs)
    return value, 0


def write_report(report: dict, path: str) -> int:
    """Write the report as STRICT JSON; returns how many values were nulled.

    ``json`` writes NaN and Infinity as bare tokens that no strict parser
    accepts. Nothing non-finite should reach here - a non-finite centre or
    extent is an "unreadable" row - so the report is encoded with
    ``allow_nan=False``; if something slips through anyway the audit is not
    thrown away for it: the value is written as null and counted in
    ``non_finite_values_nulled``.
    """
    nulled = 0
    try:
        text = json.dumps(report, indent=2, allow_nan=False)
    except ValueError:
        report, nulled = _nulled(report)
        report["non_finite_values_nulled"] = nulled
        text = json.dumps(report, indent=2, allow_nan=False)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return nulled


def _ascii(value) -> str:
    return str(value).encode("ascii", "replace").decode("ascii")


def _count(rows: list, key: str) -> dict:
    counts: dict = {}
    for r in rows:
        counts[r.get(key)] = counts.get(r.get(key), 0) + 1
    return counts


def _signed(row: dict, key: str) -> str:
    return ("%+.1f" % row[key]) if _is_number(row.get(key)) else "-"


def print_table(rows: list) -> None:
    """The console table. The name column is as wide as the longest name:
    a mesh and its ``_dense`` twin differ only at the end of theirs."""
    width = max([36] + [len(_ascii(r.get("name"))) for r in rows])
    line = ("%-8s %-" + str(width) + "s %-14s %-7s %-8s %-14s %-8s %-22s "
            "%-14s %-10s %s")
    print(line % ("asset", "name", "verdict", "N (m)", "dz (m)",
                  "tight verdict", "tight dz", "best (box)", "bracket",
                  "added", "note"))
    for r in rows:
        n = r.get("geoid_n_m", r.get("best_geoid_n_m"))
        box = {TIGHT_BOX: "tight", ROOT_BOX: "root"}.get(r.get("best_geometry"))
        print(line % (
            r["asset_id"], _ascii(r.get("name")), r.get("verdict", "?"),
            ("%.1f" % n) if _is_number(n) else "-",
            _signed(r, "vertical_vs_cameras_m"),
            r.get("tight_verdict", "?"),
            _signed(r, "tight_vertical_vs_cameras_m"),
            "%s%s" % (r.get("best_verdict", "?"),
                      (" (%s)" % box) if box else ""),
            r.get("best_bracket_verdict", "?"),
            str(r.get("date_added") or "-")[:10],
            _ascii(r.get("why") or r.get("dive_log") or "")[:60]))


def print_changes(changes: dict) -> None:
    print("\nagainst the report of %s: %d -> %d assets, %d gone, %d new, "
          "%d changed" % (changes["previous_generated"] or "(no date)",
                          changes["previous_assets"], changes["assets"],
                          len(changes["gone"]), len(changes["new"]),
                          len(changes["changed"])))
    for label in ("gone", "new"):
        for r in changes[label]:
            print("  %-7s %-8s %-22s %-24s %s" % (
                label, r.get("asset_id"), _ascii(r.get("type")),
                _ascii(r.get("date_added") or "-"), _ascii(r.get("name"))))
    for c in changes["changed"]:
        print("  changed %-8s %s: %s" % (
            c["asset_id"], _ascii(c["name"]),
            _ascii("; ".join("%s %r -> %r" % (key, c["was"][key], c["now"][key])
                             for key in c["was"]))[:200]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--flight-log", action="append", required=True,
                    help="zone-tagged dive flight log; repeat for each dive")
    ap.add_argument("--radius-m", type=float, default=30.0,
                    help="cameras within this horizontal distance of the "
                         "model centre set the expected depth")
    ap.add_argument("--max-km", type=float, default=2.0)
    ap.add_argument("--footprint-margin-m", type=float,
                    default=FOOTPRINT_MARGIN_M,
                    help="bracket test: cameras this far outside the box's "
                         "East x North footprint still count as over it")
    ap.add_argument("--above-top-m", type=float, default=CAMERAS_ABOVE_TOP_M,
                    help="bracket test: how far above the model's top its "
                         "cameras may sit")
    ap.add_argument("--out", default=None, help="write the report as JSON")
    ap.add_argument("--compare", default=None,
                    help="a previous report: list the assets gone, new and "
                         "changed since it")
    args = ap.parse_args()

    # Everything local is read AND checked before the first request: a bad
    # --compare file or an --out folder that is not there must cost nothing.
    previous = None
    if args.compare:
        with open(args.compare, encoding="utf-8") as fh:
            previous = json.load(fh)
        check_previous_report(previous, args.compare)
    if args.out:
        check_out_path(args.out)

    import requests
    from pyproj import Transformer

    to_geo = Transformer.from_crs("EPSG:4978", "EPSG:4979", always_xy=True)
    geoid_n = geoid_lookup()
    navs = []
    for path in args.flight_log:
        crs = utm_epsg(path)
        nav_rows = load_nav(path)
        if not nav_rows:
            raise SystemExit("no nav rows in %s" % path)
        navs.append({"log": path, "crs": crs, "rows": nav_rows,
                     "fwd": Transformer.from_crs("EPSG:4326", crs, always_xy=True)})

    tok = token()
    session = requests.Session()
    assets = list_assets(session, tok)
    print("assets on the account: %d\n" % len(assets))

    # dateAdded and bytes ride on the listing; an asset whose listing row
    # lacks either is asked for individually (still a GET).
    for a in assets:
        if "dateAdded" in a and "bytes" in a:
            continue
        try:
            detail = asset_detail(session, tok, a["id"])
        except Exception:                                      # noqa: BLE001
            continue
        for key in ("dateAdded", "bytes", "description"):
            if key not in a and key in detail:
                a[key] = detail[key]

    rows = audit_assets(assets, lambda i: fetch_tileset(session, tok, i),
                        navs, geoid_n, to_geo, args.radius_m, args.max_km,
                        secrets=(tok,), margin_m=args.footprint_margin_m,
                        above_top_m=args.above_top_m)

    print_table(rows)
    counts = {key: _count(rows, field) for key, field in (
        ("counts", "verdict"), ("tight_counts", "tight_verdict"),
        ("best_counts", "best_verdict"),
        ("bracket_counts", "best_bracket_verdict"))}
    print()
    for label, key in (("root box ", "counts"), ("tight box", "tight_counts"),
                       ("best box ", "best_counts"),
                       ("bracket  ", "bracket_counts")):
        print(label + "  " + "   ".join(
            "%s: %d" % kv for kv in sorted(counts[key].items(), key=str)))
    # The comparison is a footnote to the audit and must never cost it: it
    # is computed under a guard, the report is WRITTEN, and only then is the
    # listing printed.
    changes, changes_error = None, None
    if previous is not None:
        try:
            changes = compare_reports(previous, rows)
            changes["against"] = os.path.basename(args.compare)
        except Exception as exc:                               # noqa: BLE001
            changes_error = explain(exc, (tok,))
    if args.out:
        utc = datetime.datetime.now(datetime.timezone.utc)
        report = {
            "schema": SCHEMA,
            "generated": utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "generated_local": utc.astimezone().strftime("%Y-%m-%d %H:%M:%S%z"),
            "parameters": {
                "radius_m": args.radius_m, "max_km": args.max_km,
                "footprint_margin_m": args.footprint_margin_m,
                "above_top_m": args.above_top_m,
                "flight_logs": [os.path.basename(p) for p in args.flight_log]},
            "fields": FIELDS,
            "conventions": CONVENTIONS,
        }
        report.update(counts)
        if changes is not None:
            report["changes"] = changes
        if changes_error is not None:
            report["changes_error"] = changes_error
        report["assets"] = rows
        nulled = write_report(report, args.out)
        print("report ->", args.out)
        if nulled:
            print("  %d non-finite value(s) written as null" % nulled)
    if changes is not None:
        try:
            print_changes(changes)
        except Exception as exc:                               # noqa: BLE001
            print("\nthe comparison could not be printed (%s)"
                  % explain(exc, (tok,)))
    elif changes_error is not None:
        print("\nthe comparison with %s failed (%s)"
              % (_ascii(os.path.basename(args.compare)), changes_error))
    return 0


if __name__ == "__main__":
    sys.exit(main())
