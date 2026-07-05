"""Grid-based orthogonal wire autorouting helpers."""

from __future__ import annotations

from collections import defaultdict
import heapq
from numbers import Integral
from typing import Dict
from typing import List
from typing import Optional
from typing import Sequence
from typing import Tuple

import networkx as nx
import numpy as np

from .pathtracing import are_wires_connected
from .pathtracing import are_wires_horizontal_or_vertical
from .pathtracing import are_wires_intersecting_obstacles_fast

Point = Tuple[int, int]
Segment = Tuple[int, int, int, int]


def auto_route_wires(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    obstacles: np.ndarray,
    grid_x: int,
    grid_y: int,
) -> np.ndarray:
    """Route an orthogonal wire path on a grid while avoiding obstacle lines."""

    normalized_grid_x = _require_grid_value(grid_x, "grid_x")
    normalized_grid_y = _require_grid_value(grid_y, "grid_y")
    start_point = (
        _require_grid_coordinate(start_x, "start_x", normalized_grid_x),
        _require_grid_coordinate(start_y, "start_y", normalized_grid_y),
    )
    end_point = (
        _require_grid_coordinate(end_x, "end_x", normalized_grid_x),
        _require_grid_coordinate(end_y, "end_y", normalized_grid_y),
    )
    obstacle_array = _normalize_obstacles(obstacles, normalized_grid_x, normalized_grid_y)
    if start_point == end_point:
        return np.empty((0, 4), dtype=int)
    if _point_hits_any_obstacle(start_point, obstacle_array):
        raise ValueError("start point must not lie on an obstacle")
    if _point_hits_any_obstacle(end_point, obstacle_array):
        raise ValueError("end point must not lie on an obstacle")

    visibility_graph = _build_full_visibility_graph_for_terminals(
        (start_point, end_point),
        obstacle_array,
        normalized_grid_x,
        normalized_grid_y,
    )
    return _route_with_full_visibility_graph(
        start_point,
        end_point,
        visibility_graph,
        obstacle_array,
        normalized_grid_x,
        normalized_grid_y,
    )


def _require_grid_value(value: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ValueError(f"{label} must be a positive integer")
    normalized_value = int(value)
    if normalized_value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return normalized_value


def _require_grid_coordinate(value: int, label: str, spacing: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ValueError(f"{label} must be an integer on the routing grid")
    normalized_value = int(value)
    if normalized_value % spacing != 0:
        raise ValueError(f"{label} must be on the routing grid")
    return normalized_value


def _normalize_obstacles(obstacles: np.ndarray, grid_x: int, grid_y: int) -> np.ndarray:
    obstacle_array = np.asarray(obstacles)
    if obstacle_array.size == 0:
        return np.empty((0, 4), dtype=int)
    if obstacle_array.ndim != 2 or obstacle_array.shape[1] != 4:
        raise ValueError("obstacles must be a 2D array with 4 columns: X1, Y1, X2, Y2")
    normalized_rows: List[List[int]] = []
    for row_index, row in enumerate(obstacle_array):
        normalized_row: List[int] = []
        for column_index, raw_value in enumerate(row):
            if isinstance(raw_value, bool) or not isinstance(raw_value, Integral):
                raise ValueError(f"obstacles[{row_index}, {column_index}] must be an integer")
            normalized_row.append(int(raw_value))
        if normalized_row[0] % grid_x != 0 or normalized_row[2] % grid_x != 0:
            raise ValueError("obstacle X coordinates must be on the routing grid")
        if normalized_row[1] % grid_y != 0 or normalized_row[3] % grid_y != 0:
            raise ValueError("obstacle Y coordinates must be on the routing grid")
        if normalized_row[0] != normalized_row[2] and normalized_row[1] != normalized_row[3]:
            raise ValueError("obstacles must be horizontal or vertical")
        normalized_rows.append(normalized_row)
    return np.asarray(normalized_rows, dtype=int)


def _build_candidate_points(
    start_point: Point,
    end_point: Point,
    obstacles: np.ndarray,
    grid_x: int,
    grid_y: int,
) -> List[Point]:
    return _build_candidate_points_for_terminals((start_point, end_point), obstacles, grid_x, grid_y)


def _build_candidate_points_for_terminals(
    terminals: Sequence[Point],
    obstacles: np.ndarray,
    grid_x: int,
    grid_y: int,
) -> List[Point]:
    x_coordinates = {int(point[0]) for point in terminals}
    y_coordinates = {int(point[1]) for point in terminals}
    if len(obstacles) > 0:
        for obstacle in obstacles:
            x1, y1, x2, y2 = (int(value) for value in obstacle)
            x_coordinates.update({x1, x2, x1 - grid_x, x1 + grid_x, x2 - grid_x, x2 + grid_x})
            y_coordinates.update({y1, y2, y1 - grid_y, y1 + grid_y, y2 - grid_y, y2 + grid_y})
    candidate_points: List[Point] = []
    terminal_points = set(terminals)
    for x_position in sorted(x_coordinates):
        for y_position in sorted(y_coordinates):
            point = (x_position, y_position)
            if point not in terminal_points and _point_hits_any_obstacle(point, obstacles):
                continue
            candidate_points.append(point)
    return candidate_points


def _build_visibility_graph_for_terminals(
    terminals: Sequence[Point],
    obstacles: np.ndarray,
    grid_x: int,
    grid_y: int,
) -> nx.Graph:
    candidate_points = _build_candidate_points_for_terminals(terminals, obstacles, grid_x, grid_y)
    return _build_visibility_graph(candidate_points, obstacles)


def _build_full_visibility_graph_for_terminals(
    terminals: Sequence[Point],
    obstacles: np.ndarray,
    grid_x: int,
    grid_y: int,
) -> nx.Graph:
    candidate_points = _build_candidate_points_for_terminals(terminals, obstacles, grid_x, grid_y)
    return _build_full_visibility_graph(candidate_points, obstacles)


def _build_visibility_graph(candidate_points: Sequence[Point], obstacles: np.ndarray) -> nx.Graph:
    graph = nx.Graph()
    for point in candidate_points:
        graph.add_node(point)
    grouped_by_x: Dict[int, List[Point]] = defaultdict(list)
    grouped_by_y: Dict[int, List[Point]] = defaultdict(list)
    for point in candidate_points:
        grouped_by_x[point[0]].append(point)
        grouped_by_y[point[1]].append(point)
    for group_points in grouped_by_x.values():
        _add_visible_edges(graph, sorted(group_points, key=lambda point: point[1]), obstacles)
    for group_points in grouped_by_y.values():
        _add_visible_edges(graph, sorted(group_points, key=lambda point: point[0]), obstacles)
    return graph


def _build_full_visibility_graph(candidate_points: Sequence[Point], obstacles: np.ndarray) -> nx.Graph:
    graph = nx.Graph()
    for point in candidate_points:
        graph.add_node(point)
    grouped_by_x: Dict[int, List[Point]] = defaultdict(list)
    grouped_by_y: Dict[int, List[Point]] = defaultdict(list)
    for point in candidate_points:
        grouped_by_x[point[0]].append(point)
        grouped_by_y[point[1]].append(point)
    max_length = _maximum_possible_route_length(candidate_points)
    segment_penalty = (len(candidate_points) + 1) * (max_length + 1)
    for group_points in grouped_by_x.values():
        _add_full_visible_edges(graph, sorted(group_points, key=lambda point: point[1]), obstacles, segment_penalty)
    for group_points in grouped_by_y.values():
        _add_full_visible_edges(graph, sorted(group_points, key=lambda point: point[0]), obstacles, segment_penalty)
    return graph


def _maximum_possible_route_length(candidate_points: Sequence[Point]) -> int:
    if not candidate_points:
        return 0
    x_values = [point[0] for point in candidate_points]
    y_values = [point[1] for point in candidate_points]
    return (max(x_values) - min(x_values)) + (max(y_values) - min(y_values))


def _add_visible_edges(
    graph: nx.Graph,
    ordered_points: Sequence[Point],
    obstacles: np.ndarray,
) -> None:
    for first_point, second_point in zip(ordered_points, ordered_points[1:]):
        segment = (first_point[0], first_point[1], second_point[0], second_point[1])
        if _segment_hits_any_obstacle(segment, obstacles):
            continue
        graph.add_edge(first_point, second_point, length=_segment_length(segment))


def _add_full_visible_edges(
    graph: nx.Graph,
    ordered_points: Sequence[Point],
    obstacles: np.ndarray,
    segment_penalty: int,
) -> None:
    for first_index, first_point in enumerate(ordered_points):
        for second_point in ordered_points[first_index + 1 :]:
            segment = (first_point[0], first_point[1], second_point[0], second_point[1])
            if _segment_hits_any_obstacle(segment, obstacles):
                break
            graph.add_edge(first_point, second_point, weight=segment_penalty + _segment_length(segment))


def _compress_point_path(point_path: Sequence[Point]) -> np.ndarray:
    if len(point_path) < 2:
        return np.empty((0, 4), dtype=int)
    compressed_points = [point_path[0]]
    for point_index in range(1, len(point_path) - 1):
        previous_point = compressed_points[-1]
        current_point = point_path[point_index]
        next_point = point_path[point_index + 1]
        previous_horizontal = previous_point[1] == current_point[1]
        next_horizontal = current_point[1] == next_point[1]
        if previous_horizontal == next_horizontal:
            continue
        compressed_points.append(current_point)
    compressed_points.append(point_path[-1])
    wires = [
        [start_point[0], start_point[1], end_point[0], end_point[1]]
        for start_point, end_point in zip(compressed_points, compressed_points[1:])
    ]
    return np.asarray(wires, dtype=int)


def _route_with_visibility_graph(
    start_point: Point,
    end_point: Point,
    visibility_graph: nx.Graph,
    obstacles: np.ndarray,
    grid_x: int,
    grid_y: int,
) -> np.ndarray:
    if start_point not in visibility_graph or end_point not in visibility_graph:
        raise ValueError("no valid route found")
    point_path = _shortest_point_path_with_segment_penalty(visibility_graph, start_point, end_point)
    wires = _compress_point_path(point_path)
    _validate_generated_route(wires, obstacles, start_point, end_point, grid_x, grid_y)
    return wires


def _route_with_full_visibility_graph(
    start_point: Point,
    end_point: Point,
    visibility_graph: nx.Graph,
    obstacles: np.ndarray,
    grid_x: int,
    grid_y: int,
) -> np.ndarray:
    if start_point not in visibility_graph or end_point not in visibility_graph:
        raise ValueError("no valid route found")
    try:
        point_path = nx.shortest_path(visibility_graph, start_point, end_point, weight="weight")
    except (nx.NetworkXNoPath, nx.NodeNotFound) as path_error:
        raise ValueError("no valid route found") from path_error
    wires = _compress_point_path(point_path)
    _validate_generated_route(wires, obstacles, start_point, end_point, grid_x, grid_y)
    return wires


def _shortest_point_path_with_segment_penalty(
    visibility_graph: nx.Graph,
    start_point: Point,
    end_point: Point,
) -> List[Point]:
    OrientationState = Tuple[Point, str]
    start_state: OrientationState = (start_point, "")
    best_costs: Dict[OrientationState, Tuple[int, int]] = {start_state: (0, 0)}
    previous_states: Dict[OrientationState, Optional[OrientationState]] = {start_state: None}
    queue: List[Tuple[int, int, Point, str]] = [(0, 0, start_point, "")]
    final_state: Optional[OrientationState] = None
    while queue:
        segment_count, route_length, point, orientation = heapq.heappop(queue)
        current_state = (point, orientation)
        if best_costs.get(current_state) != (segment_count, route_length):
            continue
        if point == end_point:
            final_state = current_state
            break
        neighbors = sorted(
            visibility_graph.neighbors(point),
            key=lambda neighbor: (neighbor[0], neighbor[1]),
        )
        for neighbor in neighbors:
            edge_orientation = _segment_orientation(point, neighbor)
            edge_length = int(visibility_graph[point][neighbor].get("length", _segment_length((point[0], point[1], neighbor[0], neighbor[1]))))
            next_segment_count = segment_count + (0 if orientation == edge_orientation else 1)
            next_route_length = route_length + edge_length
            next_state = (neighbor, edge_orientation)
            next_cost = (next_segment_count, next_route_length)
            if next_cost >= best_costs.get(next_state, (float("inf"), float("inf"))):
                continue
            best_costs[next_state] = next_cost
            previous_states[next_state] = current_state
            heapq.heappush(queue, (next_segment_count, next_route_length, neighbor, edge_orientation))
    if final_state is None:
        raise ValueError("no valid route found")
    point_path: List[Point] = []
    current_state: Optional[OrientationState] = final_state
    while current_state is not None:
        point_path.append(current_state[0])
        current_state = previous_states[current_state]
    point_path.reverse()
    return point_path


def _segment_orientation(first_point: Point, second_point: Point) -> str:
    return "V" if first_point[0] == second_point[0] else "H"


def _validate_generated_route(
    wires: np.ndarray,
    obstacles: np.ndarray,
    start_point: Point,
    end_point: Point,
    grid_x: int,
    grid_y: int,
) -> None:
    if wires.ndim != 2 or wires.shape[1] != 4:
        raise ValueError("generated route must be a 2D array with 4 columns")
    if len(wires) == 0:
        raise ValueError("no valid route found")
    if tuple(wires[0, 0:2]) != start_point:
        raise ValueError("generated route does not start at the requested point")
    if tuple(wires[-1, 2:4]) != end_point:
        raise ValueError("generated route does not end at the requested point")
    for wire in wires:
        if wire[0] % grid_x != 0 or wire[2] % grid_x != 0:
            raise ValueError("generated route left the routing grid")
        if wire[1] % grid_y != 0 or wire[3] % grid_y != 0:
            raise ValueError("generated route left the routing grid")
    if not are_wires_horizontal_or_vertical(wires):
        raise ValueError("generated route must be horizontal or vertical only")
    if not are_wires_connected(wires):
        raise ValueError("generated route must be connected")
    if are_wires_intersecting_obstacles_fast(wires, obstacles):
        raise ValueError("generated route intersects an obstacle")


def _point_hits_any_obstacle(point: Point, obstacles: np.ndarray) -> bool:
    for obstacle in obstacles:
        if _point_on_segment(point, (int(obstacle[0]), int(obstacle[1]), int(obstacle[2]), int(obstacle[3]))):
            return True
    return False


def _point_on_segment(point: Point, segment: Segment) -> bool:
    point_x, point_y = point
    x1, y1, x2, y2 = segment
    if x1 == x2:
        return point_x == x1 and min(y1, y2) <= point_y <= max(y1, y2)
    return point_y == y1 and min(x1, x2) <= point_x <= max(x1, x2)


def _segment_hits_any_obstacle(segment: Segment, obstacles: np.ndarray) -> bool:
    for obstacle in obstacles:
        if _segments_intersect(segment, (int(obstacle[0]), int(obstacle[1]), int(obstacle[2]), int(obstacle[3]))):
            return True
    return False


def _segments_intersect(first_segment: Segment, second_segment: Segment) -> bool:
    x1a, y1a, x2a, y2a = first_segment
    x1b, y1b, x2b, y2b = second_segment
    first_vertical = x1a == x2a
    second_vertical = x1b == x2b
    if first_vertical and second_vertical:
        if x1a != x1b:
            return False
        return _ranges_overlap(y1a, y2a, y1b, y2b)
    if not first_vertical and not second_vertical:
        if y1a != y1b:
            return False
        return _ranges_overlap(x1a, x2a, x1b, x2b)
    if first_vertical:
        vertical_x, vertical_y1, vertical_y2 = x1a, y1a, y2a
        horizontal_x1, horizontal_x2, horizontal_y = x1b, x2b, y1b
    else:
        vertical_x, vertical_y1, vertical_y2 = x1b, y1b, y2b
        horizontal_x1, horizontal_x2, horizontal_y = x1a, x2a, y1a
    return min(horizontal_x1, horizontal_x2) <= vertical_x <= max(horizontal_x1, horizontal_x2) and min(vertical_y1, vertical_y2) <= horizontal_y <= max(vertical_y1, vertical_y2)


def _ranges_overlap(first_a: int, first_b: int, second_a: int, second_b: int) -> bool:
    return max(min(first_a, first_b), min(second_a, second_b)) <= min(max(first_a, first_b), max(second_a, second_b))


def _segment_length(segment: Segment) -> int:
    return abs(segment[2] - segment[0]) + abs(segment[3] - segment[1])
