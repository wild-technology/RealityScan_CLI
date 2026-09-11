"""Pre-batch density review and conservative spatial outlier candidates.

assess_spatial(points, epsg=..., thresholds=...) returns every kept/culled point,
track, density counts and an assessment_hash bound to coordinates, times,
selection, CRS and thresholds. No selection is changed and no file is deleted.
The controller owns review confirmation and the mandatory pre-batch gate.

Neighbor graphs use bounded k-nearest edges, not an all-pairs distance matrix
or an unbounded DBSCAN radius adjacency list. This is a conservative local-link
component heuristic, not exact DBSCAN: very dense k-neighbor partitions may be
split, so isolation, small size AND short burst evidence are all required.
All cameras share one geometry; camera rarity is never an outlier criterion.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components


@dataclass(frozen=True)
class SpatialThresholds:
    neighbor_radius_m: float = 50.0
    isolation_distance_m: float = 200.0
    max_candidate_images: int = 5
    max_burst_seconds: float = 30.0
    min_site_images: int = 20
    neighbor_links: int = 16
    bridge_corridor_m: float = 50.0
    bridge_angle_degrees: float = 120.0

    def validate(self):
        for key in ('neighbor_radius_m', 'isolation_distance_m', 'max_burst_seconds',
                    'bridge_corridor_m', 'bridge_angle_degrees'):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f'{key} must be finite and positive')
        for key in ('max_candidate_images', 'min_site_images', 'neighbor_links'):
            if type(getattr(self, key)) is not int or getattr(self, key) < 1:
                raise ValueError(f'{key} must be a positive integer')
        if self.max_candidate_images > 64 or self.neighbor_links > 64:
            raise ValueError('Candidate/neighbor counts must be <= 64 to bound memory')
        if self.min_site_images <= self.max_candidate_images:
            raise ValueError('min_site_images must exceed max_candidate_images')
        if self.isolation_distance_m <= self.neighbor_radius_m:
            raise ValueError('Isolation distance must exceed the local neighbor radius')
        if not 90 <= self.bridge_angle_degrees < 180:
            raise ValueError('Bridge angle must be in [90, 180) degrees')


def _zone(epsg: int) -> str:
    if type(epsg) is not int or not (32601 <= epsg <= 32660 or 32701 <= epsg <= 32760):
        raise ValueError('An explicit WGS84 UTM EPSG integer is required')
    return str(epsg % 100) + ('N' if epsg < 32700 else 'S')


def points_from_matches(items, frame: pd.DataFrame, matches: dict, *, epsg: int) -> list[dict]:
    """Adapt navigation_quality matches without inventing poses for unmatched files.

    For a kept/culled display, request include_excluded/include_duplicates when
    building navigation matches. All required included frames must be matched
    before the controller can authorize processing; this adapter is no gate.
    """
    zone = _zone(epsg)
    if 'utm_zone' not in frame or set(frame['utm_zone'].astype(str)) != {zone}:
        raise ValueError('Navigation UTM zone does not match the requested EPSG')
    by_path = {item.path: item for item in items}
    if len(by_path) != len(items):
        raise ValueError('Inventory contains duplicate paths')
    points = []
    for match in matches['matched']:
        if match['path'] not in by_path:
            raise ValueError('Match references an unknown inventory path')
        index = match['nav_row']
        if type(index) is not int or not 0 <= index < len(frame):
            raise ValueError('Match references an invalid navigation row')
        image = by_path[match['path']]
        row = frame.iloc[index]
        points.append({'path': image.path, 'x': float(row['kalman_x']), 'y': float(row['kalman_y']),
                       'camera': image.camera, 'time': image.timestamp_utc, 'epsg': epsg,
                       'excluded': not image.included or bool(image.duplicate_of)})
    return points


def assess_spatial(points: list[dict], *, epsg: int,
                   thresholds: SpatialThresholds | dict | None = None,
                   track: list[list[float]] | None = None) -> dict:
    """Return candidate evidence and density for 100k-scale float64 point sets.

    A candidate needs a small local component, short temporal span, separation
    from ALL other observations, a substantial survey reference, and no corridor
    between substantial sites. Large separate sites, long sparse observations and
    potential bridges remain unflagged. Candidates are suggestions, never rejects.
    Excluded points still provide geometric evidence so toggling one cannot make
    its neighboring camera appear accidentally isolated; their densities and the
    display selection are nevertheless reported separately.
    """
    zone = _zone(epsg)
    config = SpatialThresholds(**thresholds) if isinstance(thresholds, dict) else thresholds or SpatialThresholds()
    if not isinstance(config, SpatialThresholds):
        raise ValueError('Invalid spatial thresholds')
    config.validate()
    normalized, seen = [], set()
    for raw in points:
        path = raw.get('path')
        if not isinstance(path, str) or not path or path.casefold() in seen:
            raise ValueError('Spatial point paths must be nonempty and unique')
        seen.add(path.casefold())
        if raw.get('epsg', epsg) != epsg or raw.get('utm_zone', zone) != zone:
            raise ValueError('Point CRS/zone does not match assessment EPSG')
        if not isinstance(raw.get('camera'), str) or not raw['camera']:
            raise ValueError('Spatial points require camera identity')
        if type(raw.get('excluded', False)) is not bool:
            raise ValueError('Point excluded selection must be boolean')
        if isinstance(raw.get('x'), bool) or isinstance(raw.get('y'), bool):
            raise ValueError('Spatial coordinates must be finite float64 values')
        try:
            x, y = float(raw['x']), float(raw['y'])
            timestamp = pd.Timestamp(raw['time'])
            if not math.isfinite(x) or not math.isfinite(y) or pd.isna(timestamp) or timestamp.tzinfo is None:
                raise ValueError('Invalid pose/time')
            timestamp = timestamp.tz_convert('UTC')
            instant = timestamp.value
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError('Spatial points require finite XY and valid timezone-aware times') from exc
        normalized.append({'path': path, 'x': x, 'y': y, 'camera': raw['camera'],
                           'time': timestamp.isoformat(), 'excluded': raw.get('excluded', False),
                           '_time_ns': instant})
    normalized.sort(key=lambda p: (p['path'].casefold(), p['path']))
    xy = np.asarray([[p['x'], p['y']] for p in normalized], dtype=np.float64).reshape((-1, 2))
    if track is None:
        trajectory = [[p['x'], p['y']] for p in sorted(normalized, key=lambda p: (p['_time_ns'], p['path']))]
    else:
        array = np.asarray(track, dtype=np.float64)
        if array.size == 0:
            array = array.reshape((0, 2))
        if array.ndim != 2 or array.shape[1] != 2 or not np.isfinite(array).all():
            raise ValueError('Track must contain finite XY coordinate pairs in the same EPSG')
        trajectory = array.tolist()
    payload = {'schema': 1, 'epsg': epsg, 'thresholds': asdict(config),
               'points': [{k: v for k, v in p.items() if k != '_time_ns'} for p in normalized],
               'track': trajectory}
    assessment_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False,
                                                separators=(',', ':')).encode()).hexdigest()
    n = len(normalized)
    labels, densities, kept_densities = np.zeros(n, dtype=int), np.zeros(n, dtype=int), np.zeros(n, dtype=int)
    components = []
    if n:
        # Repeated matched poses are common across cameras and duplicate copies.
        # Collapse exact coordinates for graph queries; retain every observation
        # for counts, time evidence, selection and output. This also avoids the
        # expensive all-tied nearest-neighbor case on 100k coincident poses.
        unique_xy, inverse = np.unique(xy, axis=0, return_inverse=True)
        geometry_n = len(unique_xy)
        tree = cKDTree(unique_xy)
        k = min(geometry_n, config.neighbor_links + 1)
        distances, neighbors = tree.query(unique_xy, k=k, workers=1)
        distances, neighbors = distances.reshape(geometry_n, k), neighbors.reshape(geometry_n, k)
        rows = np.repeat(np.arange(geometry_n), k)
        columns = neighbors.ravel()
        valid = (distances.ravel() <= config.neighbor_radius_m) & (rows != columns)
        graph = coo_matrix((np.ones(int(valid.sum()), dtype=np.uint8), (rows[valid], columns[valid])),
                           shape=(geometry_n, geometry_n)).tocsr()
        _, geometry_labels = connected_components(graph, directed=False)
        labels = geometry_labels[inverse]
        densities = cKDTree(xy).query_ball_point(unique_xy, config.neighbor_radius_m,
                                                return_length=True, workers=1)[inverse]
        keep = np.asarray([not p['excluded'] for p in normalized])
        if keep.any():
            kept_densities = cKDTree(xy[keep]).query_ball_point(unique_xy, config.neighbor_radius_m,
                                                              return_length=True, workers=1)[inverse]
        # One sort/split replaces a full scan per component (all-isolated case).
        order = np.argsort(labels, kind='stable')
        groups = np.split(order, np.flatnonzero(np.diff(labels[order])) + 1)
        supported = [group for group in groups if len(group) >= config.min_site_images]
        centers = np.asarray([xy[group].mean(axis=0) for group in supported], dtype=np.float64)
        center_tree = cKDTree(centers) if len(centers) else None
        for group in groups:
            size = len(group)
            duration = (max(normalized[i]['_time_ns'] for i in group)
                        - min(normalized[i]['_time_ns'] for i in group)) / 1e9
            candidate, isolation, bridge = False, None, False
            reason = 'Supported site' if size >= config.min_site_images else 'Insufficient combined isolation/burst evidence'
            if center_tree is not None and size <= config.max_candidate_images and duration <= config.max_burst_seconds:
                # At most max_candidate_images+1 neighbors ensures an external
                # point, with a bounded query even for coincident coordinates.
                external_k = min(geometry_n, config.max_candidate_images + 1)
                dd, nn = tree.query(xy[group], k=external_k, workers=1)
                dd, nn = dd.reshape(size, external_k), nn.reshape(size, external_k)
                external = geometry_labels[nn] != labels[group[0]]
                isolation = float(dd[external].min()) if external.any() else None
                if isolation is not None and isolation >= config.isolation_distance_m:
                    center = xy[group].mean(axis=0)
                    if len(centers) >= 2:
                        _, nearest = center_tree.query(center, k=2)
                        a, b = centers[nearest]
                        ab = b - a
                        length2 = float(ab @ ab)
                        if length2:
                            fraction = float((center - a) @ ab / length2)
                            cross_distance = float(np.linalg.norm(center - (a + fraction * ab)))
                            va, vb = a - center, b - center
                            denominator = float(np.linalg.norm(va) * np.linalg.norm(vb))
                            cosine = float(va @ vb / denominator) if denominator else 1.0
                            bridge = (0 <= fraction <= 1 and cross_distance <= config.bridge_corridor_m
                                      and cosine <= math.cos(math.radians(config.bridge_angle_degrees)))
                    candidate = not bridge
                    reason = ('Possible bridge between supported sites; retain for review' if bridge else
                              f'Candidate only: {size} images in {duration:.1f}s, isolated by {isolation:.1f}m')
            components.append({'component': int(labels[group[0]]), 'images': size,
                               'burst_seconds': duration, 'isolation_m': isolation,
                               'possible_bridge': bridge, 'candidate': candidate, 'reason': reason})
    evidence = {entry['component']: entry for entry in components}
    result_points = []
    for index, point in enumerate(normalized):
        entry = evidence[int(labels[index])]
        result_points.append({**{k: v for k, v in point.items() if k != '_time_ns'},
                              'outlier': entry['candidate'], 'reason': entry['reason'],
                              'component': int(labels[index]), 'neighbors': int(densities[index]),
                              'kept_neighbors': int(kept_densities[index])})
    return {'schema': 1, 'epsg': epsg, 'assessment_hash': assessment_hash,
            'thresholds': asdict(config), 'points': result_points, 'track': trajectory,
            'components': components, 'candidate_count': sum(p['outlier'] for p in result_points),
            'kept_count': sum(not p['excluded'] for p in result_points),
            'excluded_count': sum(p['excluded'] for p in result_points),
            'automatic_exclusion': False,
            'limitations': ['Candidate evidence is not a science rejection or a deletion instruction',
                            'Separate small survey sites may resemble accidental bursts; owner decides',
                            'Bounded local-link components are not exact DBSCAN']}
