#!/usr/bin/env python3
"""Metric-scale oracle for aligned components.

The pipeline's automated checks have historically measured only QUANTITY
(cameras registered, components produced). This measures QUALITY: whether
a solved component is metrically consistent with the nav trajectory that
georeferenced it.

Method: the ratio of solved-to-nav distance over many random camera
pairs. Pairwise distance is invariant to translation AND rotation, so the
figure is meaningful even when a component's absolute placement is
arbitrary - which it often is (see FINDINGS 2026-07-25).

    ratio ~= 1.0   metrically sound
    ratio << 1.0   solve is SMALLER than reality (scale collapse)
    wide IQR       not a similarity error - drift, fold, or mixed bodies

Discovered by this measurement: fresh-run zone_1 hull components solved
at 0.175 and 0.220 (5.7x / 4.5x too small) while the bow and other zones
solved at ~1.0. A uniform scale error is invisible in the viewer, so
nothing upstream caught it.

PROMOTED out of testing/ on 2026-07-26: this is a DELIVERABLE GATE, called by
merge_zones before any model is generated, so it must not live beside the unit
tests. A 0.236-scale H2024 component passed every existing check and reached a
deliverable because nothing called this module (review finding D3).

Positions come from the pose XMPs of an identity_r<K> harvest directory
(zone-scene exports carry real stems - B10 only degrades imported-
component scenes). Components are separated by successive difference,
exactly as the align workflow's identity loop defines them.
"""
from __future__ import annotations

import glob
import math
import os
import random
import re

POS_RE = re.compile(r'<xcr:Position>([^<]+)</xcr:Position>|xcr:Position="([^"]+)"')


def load_solved_positions(identity_dir: str) -> dict[str, tuple]:
    """{stem_lower: (x, y, z)} from an identity_r<K> harvest directory."""
    out = {}
    for path in glob.glob(os.path.join(identity_dir, '*.xmp')):
        try:
            with open(path, encoding='utf-8', errors='replace') as fh:
                text = fh.read()
        except OSError:
            continue
        m = POS_RE.search(text)
        if m:
            raw = m.group(1) or m.group(2)
            out[os.path.splitext(os.path.basename(path))[0].lower()] = tuple(
                float(v) for v in raw.split())
    return out


def load_nav_positions(flight_log: str) -> dict[str, tuple]:
    """{stem_lower: (x, y, alt)} from a flight_log_*_UTM.txt.

    Keyed on the BASENAME stem. Every other site here builds its stems from
    XMP filenames (``basename`` + ``splitext``), but in pool layout the log's
    filename column is a full canonical path (FLIGHTLOG_ARCHITECTURE), so
    keying on ``splitext(parts[0])`` produced full-path keys that matched
    none of them and every component reported scale UNMEASURED - "too few
    images shared with the nav table". Observed on NA165/H2060: all 20.
    """
    out = {}
    with open(flight_log, encoding='utf-8', errors='replace') as fh:
        for line in list(fh)[1:]:
            parts = line.split(';')
            if len(parts) > 3 and parts[1].strip():
                raw = parts[0].strip().strip('"')
                stem = os.path.splitext(
                    os.path.basename(raw.replace('\\', '/')))[0].lower()
                out[stem] = (
                    float(parts[1]), float(parts[2]), float(parts[3]))
    return out


def component_members(components_dir: str) -> list[set]:
    """Member stem sets per component, by successive difference over the
    identity_r<K> harvest directories (maximal-first, same as the align
    workflow's own definition)."""
    rounds = []
    k = 0
    while os.path.isdir(os.path.join(components_dir, f'identity_r{k}')):
        stems = {os.path.splitext(f)[0].lower()
                 for f in os.listdir(os.path.join(components_dir, f'identity_r{k}'))
                 if f.lower().endswith('.xmp')}
        if not stems:
            break
        rounds.append(stems)
        k += 1
    return [rounds[i] - (rounds[i + 1] if i + 1 < len(rounds) else set())
            for i in range(len(rounds))]


def solved_position_cloud(identity_dir: str) -> list[tuple]:
    """EVERY pose position in a harvest dir, identity-free.

    For FUSED components the sidecars are ORDINAL (B10) so stems carry no
    identity and the stem-pairing oracle returns UNMEASURED - which is how
    the scale gate correctly blocked the H2024 hull's model. The quantile
    method below measures those components anyway. The frame is the model
    frame, not UTM; irrelevant, because distance ratios are rigid-invariant
    and the scale factor is exactly what is measured."""
    return list(load_solved_positions(identity_dir).values())


def member_multiset(manifest: dict, components_root: str) -> list[str]:
    """Camera-level member list of a component.

    A fused manifest's `images` is the unique-basename UNION of its inputs,
    but the scene holds one camera per input OCCURRENCE (the batcher copies
    overlap images into two zones), so the nav multiset must be the
    CONCATENATION of the attributed input manifests' members. Unfused
    components are their own multiset. Falls back to the union when an
    input manifest is unavailable (e.g. a second-round fusion)."""
    inputs = (manifest.get('attribution') or {}).get('inputs') or []
    if not inputs:
        return list(manifest.get('images') or [])
    members: list[str] = []
    for key in inputs:
        try:
            zone, comp = key.split('/', 1)
        except ValueError:
            return list(manifest.get('images') or [])
        path = os.path.join(components_root, zone,
                            comp + '.rsalign.manifest.json')
        if not os.path.isfile(path):
            return list(manifest.get('images') or [])
        import json
        with open(path, encoding='utf-8') as fh:
            members.extend(json.load(fh).get('images') or [])
    return members


def nav_position_multiset(flight_log: str, members: list[str]) -> list[tuple]:
    """Nav position per MEMBER OCCURRENCE (duplicated basenames appear as
    many times as the scene holds cameras for them)."""
    table = load_nav_positions(flight_log)
    out = []
    for m in members:
        stem = os.path.splitext(m)[0].lower()
        if stem in table:
            out.append(table[stem])
    return out


def quantile_ratio_scale(solved: list[tuple], nav: list[tuple]) -> dict | None:
    """Correspondence-free similarity scale via matched quantiles of
    distance-from-centroid; returns the same stats shape as scale_ratio.

    Under a similarity transform, SORTED distances-from-centroid of the same
    camera multiset correspond rank-for-rank, so quantile ratios give median
    + IQR without any pairing. Validated 2026-07-29: known-good zone_1_c1
    measured 1.045 vs the stem oracle's 1.023 (same verdict); the hull's
    clouds shrunk by 0.236 FAIL at 0.235. Gross non-similarity (drift, a
    fold) widens the IQR and trips the same wide-IQR call-out as the stem
    oracle."""
    if len(solved) < 30 or len(nav) < 30:
        return None
    if abs(len(solved) - len(nav)) / max(len(solved), len(nav)) > 0.05:
        return None

    def sorted_radii(points: list[tuple]) -> list[float]:
        n = len(points)
        cx = sum(p[0] for p in points) / n
        cy = sum(p[1] for p in points) / n
        cz = sum(p[2] for p in points) / n
        return sorted(math.dist(p, (cx, cy, cz)) for p in points)

    rs = sorted_radii(solved)
    rn = sorted_radii(nav)

    def quantile(sorted_vals: list[float], q: float) -> float:
        idx = q * (len(sorted_vals) - 1)
        lo = int(idx)
        hi = min(lo + 1, len(sorted_vals) - 1)
        frac = idx - lo
        return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac

    qs = [0.05 + 0.01 * i for i in range(91)]     # 5th..95th, trimmed tails
    ratios = []
    for q in qs:
        denom = quantile(rn, q)
        if denom > 1e-6:
            ratios.append(quantile(rs, q) / denom)
    if len(ratios) < 30:
        return None
    ratios.sort()
    return {
        'median': quantile(ratios, 0.5),
        'iqr_low': quantile(ratios, 0.25),
        'iqr_high': quantile(ratios, 0.75),
        'cameras': len(solved),
    }


def scale_ratio(members: set, solved: dict, nav: dict,
                samples: int = 4000, min_nav_distance: float = 3.0,
                seed: int = 5) -> dict | None:
    """Median/IQR of solved/nav pairwise-distance ratio for one component."""
    common = [s for s in members if s in solved and s in nav]
    if len(common) < 30:
        return None
    rng = random.Random(seed)
    vals = []
    for _ in range(samples):
        a, b = rng.sample(common, 2)
        d_nav = math.dist(nav[a], nav[b])
        if d_nav > min_nav_distance:
            vals.append(math.dist(solved[a], solved[b]) / d_nav)
    if not vals:
        return None
    vals.sort()
    n = len(vals)
    return {'cameras': len(common), 'median': vals[n // 2],
            'iqr_low': vals[n // 4], 'iqr_high': vals[3 * n // 4], 'pairs': n}


DEFAULT_SCALE_MIN = 0.90
DEFAULT_SCALE_MAX = 1.10


def scale_for_images(images: list, components_dir: str, nav: dict) -> dict | None:
    """Scale for ONE component identified by its manifest image list.

    Preferred over report() when the caller already knows exactly which images
    belong to the component: it needs no successive-difference reconstruction
    and cannot mis-attribute a component by ordinal position. Returns None when
    the component cannot be measured (no harvest on disk, or fewer than 30
    images shared between the harvest and the nav table) - callers must treat
    None as UNMEASURED, never as passing.
    """
    solved = load_solved_positions(os.path.join(components_dir, 'identity_r0'))
    if not solved:
        return None
    members = {os.path.splitext(str(i))[0].lower() for i in images}
    return scale_ratio(members, solved, nav)


def verdict(stats: dict | None, scale_min: float = DEFAULT_SCALE_MIN,
            scale_max: float = DEFAULT_SCALE_MAX) -> tuple[str, str]:
    """(status, human explanation) for one component's scale.

    status is 'pass', 'fail' or 'unmeasured'. A wide IQR passes the band check
    but is called out, because by construction it means something other than a
    similarity error - drift, a fold, or mixed bodies.
    """
    if stats is None:
        return 'unmeasured', ('no pose harvest on disk, or too few images shared '
                              'with the nav table - scale could not be measured')
    median = stats['median']
    width = stats['iqr_high'] - stats['iqr_low']
    if not (scale_min <= median <= scale_max):
        return 'fail', (f"scale {median:.3f} is outside "
                        f"{scale_min:.2f}-{scale_max:.2f} "
                        f"(IQR {stats['iqr_low']:.3f}-{stats['iqr_high']:.3f})")
    if width > 0.15:
        return 'pass', (f"scale {median:.3f} in band but IQR is wide "
                        f"({width:.3f}) - suggests drift or a fold, not a clean "
                        f"similarity error")
    return 'pass', f"scale {median:.3f} (IQR width {width:.3f})"


def report(components_dir: str, flight_log: str) -> list[dict]:
    """Per-component scale for a finished align. Component 0 is maximal."""
    solved = load_solved_positions(os.path.join(components_dir, 'identity_r0'))
    nav = load_nav_positions(flight_log)
    rows = []
    for i, members in enumerate(component_members(components_dir)):
        stats = scale_ratio(members, solved, nav)
        if stats:
            stats['component'] = i
            rows.append(stats)
    return rows


if __name__ == '__main__':
    import sys
    if len(sys.argv) != 3:
        print('usage: scale_oracle.py <components_dir> <flight_log>')
        raise SystemExit(2)
    for row in report(sys.argv[1], sys.argv[2]):
        print('c{component}: {cameras:5d} cams  scale {median:.3f}  '
              'IQR {iqr_low:.3f}-{iqr_high:.3f}'.format(**row))
