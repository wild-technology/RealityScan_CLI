#!/usr/bin/env python3
"""Audit every Cesium ion asset on the account against the dives' own nav:
is it in the right place, and is its DEPTH on the right vertical datum?

READ ONLY. Lists assets and reads each finished tileset's root transform and
bounding box; deletes nothing and changes nothing on ion.

For each 3D Tiles asset:

  1. MODEL CENTRE - ``boundingVolume.box[0:3]`` carried through
     ``root.transform`` (never the transform's translation alone: ion puts the
     local origin INSIDE the model, so origin-to-centre grows with model size
     and that comparison flagged exactly the largest H2063 components,
     2026-09-23).
  2. WHICH DIVE - the nearest nav track among the flight logs given with
     ``--flight-log`` (zone-tagged: the UTM zone comes from the filename).
     Further than ``--max-km`` from every track = "unmatched".
  3. EXPECTED HEIGHT - median nav Alt of the cameras within ``--radius-m`` of
     the centre (Alt is -depth below the sea surface, an ORTHOMETRIC height)
     plus the EGM2008 undulation N there. The model sits below its cameras
     by the stand-off, so a correctly placed asset reads a few metres to
     ~15 m under this; one placed WITHOUT the geoid reads ~N metres under it
     (25 m at NA165, 66-73 m at NA168).

Verdicts: ``ok`` (horizontal within the track, vertical offset > -N/2),
``MISSING-GEOID`` (vertical offset within N/2 of -N), ``FAULT`` (anything
else, or no root.transform - raw ECEF tiles quantise to ~0.72 m).

Needs the EGM2008 grid locally or PROJ network access; without it PROJ would
silently return N = 0, so the transform is built with allow_ballpark=False
and fails instead.

Usage:
    python validate_cesium_assets.py --flight-log <log> [--flight-log <log>...]
        [--out report.json]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

API = "https://api.cesium.com"


def token() -> str:
    from publish_cesium import ion_token_from_environment
    tok = ion_token_from_environment()
    if not tok:
        raise SystemExit("no CESIUM_ION_TOKEN available")
    return tok


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


def tileset_centre(session, tok: str, asset_id: int):
    """(centre_ecef or None, has_transform, extent_m, radius_m)."""
    h = {"Authorization": "Bearer " + tok}
    e = session.get("%s/v1/assets/%d/endpoint" % (API, asset_id),
                    headers=h, timeout=60)
    e.raise_for_status()
    ep = e.json()
    ts = session.get(ep["url"],
                     headers={"Authorization": "Bearer " + ep["accessToken"]},
                     timeout=120).json()
    root = ts.get("root") or {}
    m = root.get("transform")
    box = (root.get("boundingVolume") or {}).get("box")
    extent = radius = None
    if box and len(box) >= 12:
        hx, hy, hz = box[3:6], box[6:9], box[9:12]
        extent = [2 * math.sqrt(sum(c * c for c in v)) for v in (hx, hy, hz)]
        radius = math.sqrt(sum((a + b + c) ** 2 for a, b, c in zip(hx, hy, hz)))
    if not m or len(m) < 16:
        return None, False, extent, radius
    cx, cy, cz = (box[0], box[1], box[2]) if box and len(box) >= 3 else (0.0, 0.0, 0.0)
    ecef = (m[0] * cx + m[4] * cy + m[8] * cz + m[12],
            m[1] * cx + m[5] * cy + m[9] * cz + m[13],
            m[2] * cx + m[6] * cy + m[10] * cz + m[14])
    return tuple(float(v) for v in ecef), True, extent, radius


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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--flight-log", action="append", required=True,
                    help="zone-tagged dive flight log; repeat for each dive")
    ap.add_argument("--radius-m", type=float, default=30.0,
                    help="cameras within this horizontal distance of the "
                         "model centre set the expected depth")
    ap.add_argument("--max-km", type=float, default=2.0)
    ap.add_argument("--out", default=None, help="write the report as JSON")
    args = ap.parse_args()

    import requests
    from pyproj import Transformer

    to_geo = Transformer.from_crs("EPSG:4978", "EPSG:4979", always_xy=True)
    geoid = Transformer.from_crs("EPSG:9518", "EPSG:4979", always_xy=True,
                                 allow_ballpark=False)
    navs = []
    for path in args.flight_log:
        crs = utm_epsg(path)
        navs.append({"log": path, "crs": crs, "rows": load_nav(path),
                     "fwd": Transformer.from_crs("EPSG:4326", crs, always_xy=True)})

    tok = token()
    session = requests.Session()
    assets = list_assets(session, tok)
    print("assets on the account: %d\n" % len(assets))

    rows = []
    for a in sorted(assets, key=lambda x: x.get("id", 0)):
        rec = {"asset_id": a.get("id"), "name": a.get("name"),
               "type": a.get("type"), "status": a.get("status")}
        rows.append(rec)
        if a.get("type") != "3DTILES" or a.get("status") != "COMPLETE":
            rec["verdict"] = "skipped"
            rec["why"] = "%s/%s" % (a.get("type"), a.get("status"))
            continue
        try:
            ecef, has_t, extent, radius = tileset_centre(session, tok, a["id"])
        except Exception as exc:                               # noqa: BLE001
            rec["verdict"], rec["why"] = "unreadable", str(exc)[:160]
            continue
        rec.update(extent_m=extent, radius_m=radius, has_root_transform=has_t)
        if not has_t:
            rec["verdict"] = "FAULT"
            rec["why"] = "no root.transform - raw ECEF tiles (float32, ~0.72 m)"
            continue
        lon, lat, h = to_geo.transform(*ecef)
        rec.update(lon=lon, lat=lat, height_ellipsoidal_m=h)

        best = None
        for nv in navs:
            e, n = nv["fwd"].transform(lon, lat)
            d2 = [((x - e) ** 2 + (y - n) ** 2, z) for x, y, z in nv["rows"]]
            dmin = math.sqrt(min(d for d, _z in d2))
            if best is None or dmin < best[0]:
                near = [z for d, z in d2 if d <= args.radius_m ** 2]
                best = (dmin, nv["log"], near)
        dmin, log, near = best
        rec["dive_log"], rec["distance_to_track_m"] = os.path.basename(log), dmin
        if dmin > args.max_km * 1000:
            rec["verdict"], rec["why"] = "unmatched", "%.1f km from every nav track" % (dmin / 1000)
            continue
        if not near:
            rec["verdict"], rec["why"] = "FAULT", "%.0f m from the nav track" % dmin
            continue
        N = geoid.transform(lon, lat, 0.0)[2]
        expected = statistics.median(near) + N
        dv = h - expected
        rec.update(geoid_n_m=N, nav_alt_median_m=statistics.median(near),
                   expected_height_m=expected, vertical_vs_cameras_m=dv)
        if abs(dv + N) <= N / 2:
            rec["verdict"] = "MISSING-GEOID"
            rec["why"] = "%.1f m under the cameras = the %.1f m undulation" % (-dv, N)
        elif dv > -N / 2 and dv < 10:
            rec["verdict"] = "ok"
        else:
            rec["verdict"] = "FAULT"
            rec["why"] = "vertical %+.1f m vs cameras (N %.1f)" % (dv, N)

    print("%-8s %-36s %-14s %-9s %-9s %s" % ("asset", "name", "verdict",
                                             "N (m)", "dz (m)", "note"))
    for r in rows:
        print("%-8s %-36s %-14s %-9s %-9s %s" % (
            r["asset_id"], str(r.get("name"))[:36], r.get("verdict", "?"),
            ("%.1f" % r["geoid_n_m"]) if "geoid_n_m" in r else "-",
            ("%+.1f" % r["vertical_vs_cameras_m"]) if "vertical_vs_cameras_m" in r else "-",
            (r.get("why") or r.get("dive_log") or "")[:60]))
    counts = {}
    for r in rows:
        counts[r.get("verdict")] = counts.get(r.get("verdict"), 0) + 1
    print("\n" + "   ".join("%s: %d" % kv for kv in sorted(counts.items())))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump({"assets": rows}, fh, indent=2)
        print("report ->", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
