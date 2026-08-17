"""Topology-preserving cleanup for routed schematic wire segments.

The consolidation pass adapts the degree-aware collinear trace simplification
used by the MIT-licensed ``kicad-tools`` project (Copyright (c) 2024 RJ
Walters).  It intentionally works on this project's plain segment tuples and
does not depend on ``kicad-tools``.
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, Iterable, List, Mapping, Optional, Set, Tuple

Point = Tuple[float, float]
Segment = Tuple[Point, Point]

__all__ = ["optimize_routed_traces", "trace_cost"]


def _point_key(point: Point) -> Point:
    return round(point[0], 6), round(point[1], 6)


def _segment_key(segment: Segment) -> Tuple[Point, Point]:
    first, second = _point_key(segment[0]), _point_key(segment[1])
    return (first, second) if first <= second else (second, first)


def _deduplicate(segments: Iterable[Segment]) -> List[Segment]:
    unique: Dict[Tuple[Point, Point], Segment] = {}
    for segment in segments:
        first, second = _point_key(segment[0]), _point_key(segment[1])
        if first == second:
            continue
        key = (first, second) if first <= second else (second, first)
        unique.setdefault(key, (first, second))
    return list(unique.values())


def _merge_at_degree_two(segments: List[Segment], protected_points: Set[Point]) -> Tuple[List[Segment], bool]:
    degree: Counter[Point] = Counter()
    incident: Dict[Point, List[int]] = {}
    for index, (first, second) in enumerate(segments):
        for point in (first, second):
            key = _point_key(point)
            degree[key] += 1
            incident.setdefault(key, []).append(index)
    for junction in sorted(incident):
        if degree[junction] != 2 or junction in protected_points:
            continue
        first_index, second_index = incident[junction]
        first_segment, second_segment = segments[first_index], segments[second_index]
        first_other = first_segment[1] if _point_key(first_segment[0]) == junction else first_segment[0]
        second_other = second_segment[1] if _point_key(second_segment[0]) == junction else second_segment[0]
        horizontal = abs(first_other[1] - junction[1]) < 1e-9 and abs(second_other[1] - junction[1]) < 1e-9
        vertical = abs(first_other[0] - junction[0]) < 1e-9 and abs(second_other[0] - junction[0]) < 1e-9
        if not (horizontal or vertical):
            continue
        retained = [segment for index, segment in enumerate(segments) if index not in (first_index, second_index)]
        retained.append((_point_key(first_other), _point_key(second_other)))
        return _deduplicate(retained), True
    return segments, False


def optimize_routed_traces(
    segments_by_net: Mapping[str, Iterable[Segment]],
    passes: int = 8,
    protected_points_by_net: Optional[Mapping[str, Iterable[Point]]] = None,
) -> Dict[str, List[Segment]]:
    """Deduplicate and consolidate collinear degree-two trace chains.

    Only adjacent collinear segments are replaced by their exact union. Branch
    points, crossings, corners, and terminal junctions therefore remain fixed.
    """

    optimized: Dict[str, List[Segment]] = {}
    for net_name, raw_segments in segments_by_net.items():
        segments = _deduplicate(raw_segments)
        protected_points = {
            _point_key(point)
            for point in (protected_points_by_net or {}).get(net_name, ())
        }
        for _pass in range(max(0, passes)):
            segments, changed = _merge_at_degree_two(segments, protected_points)
            if not changed:
                break
        optimized[net_name] = segments
    return optimized


def trace_cost(segments_by_net: Mapping[str, Iterable[Segment]], fallback_count: int = 0) -> Tuple[int, float, int]:
    """Return a lexicographic routing score: fallbacks, length, segments."""

    length = 0.0
    segment_count = 0
    for segments in segments_by_net.values():
        for first, second in segments:
            length += abs(second[0] - first[0]) + abs(second[1] - first[1])
            segment_count += 1
    return fallback_count, round(length, 6), segment_count
