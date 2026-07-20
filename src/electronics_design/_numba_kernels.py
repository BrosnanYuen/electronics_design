"""Numba kernels for routing and path-tracing hot loops."""

from __future__ import annotations

import heapq

import numpy as np
from numba import njit
from numba import prange
from numba import set_num_threads

from ._parallel import parallel_worker_count


set_num_threads(parallel_worker_count())


@njit(cache=True, inline="always")
def _ranges_overlap(a1, a2, b1, b2):
    return max(min(a1, a2), min(b1, b2)) <= min(max(a1, a2), max(b1, b2))


@njit(cache=True, inline="always")
def _lines_intersect_values(x1a, y1a, x2a, y2a, x1b, y1b, x2b, y2b):
    a_vertical = x1a == x2a
    b_vertical = x1b == x2b
    if a_vertical and b_vertical:
        return x1a == x1b and _ranges_overlap(y1a, y2a, y1b, y2b)
    if not a_vertical and not b_vertical:
        return y1a == y1b and _ranges_overlap(x1a, x2a, x1b, x2b)
    if a_vertical:
        vertical_x, vertical_y1, vertical_y2 = x1a, y1a, y2a
        horizontal_x1, horizontal_x2, horizontal_y = x1b, x2b, y1b
    else:
        vertical_x, vertical_y1, vertical_y2 = x1b, y1b, y2b
        horizontal_x1, horizontal_x2, horizontal_y = x1a, x2a, y1a
    return (
        min(horizontal_x1, horizontal_x2) <= vertical_x <= max(horizontal_x1, horizontal_x2)
        and min(vertical_y1, vertical_y2) <= horizontal_y <= max(vertical_y1, vertical_y2)
    )


@njit(cache=True, nogil=True)
def intersection_matrix_serial(wires: np.ndarray, obstacles: np.ndarray) -> np.ndarray:
    intersections = np.zeros((len(wires), len(obstacles)), dtype=np.bool_)
    for wire_index in range(len(wires)):
        wire = wires[wire_index]
        for obstacle_index in range(len(obstacles)):
            obstacle = obstacles[obstacle_index]
            intersections[wire_index, obstacle_index] = _lines_intersect_values(
                wire[0], wire[1], wire[2], wire[3],
                obstacle[0], obstacle[1], obstacle[2], obstacle[3],
            )
    return intersections


@njit(cache=True, nogil=True, parallel=True)
def intersection_matrix_parallel(wires: np.ndarray, obstacles: np.ndarray) -> np.ndarray:
    intersections = np.zeros((len(wires), len(obstacles)), dtype=np.bool_)
    for wire_index in prange(len(wires)):
        wire = wires[wire_index]
        for obstacle_index in range(len(obstacles)):
            obstacle = obstacles[obstacle_index]
            intersections[wire_index, obstacle_index] = _lines_intersect_values(
                wire[0], wire[1], wire[2], wire[3],
                obstacle[0], obstacle[1], obstacle[2], obstacle[3],
            )
    return intersections


@njit(cache=True, nogil=True)
def any_intersection_serial(wires: np.ndarray, obstacles: np.ndarray) -> bool:
    for wire_index in range(len(wires)):
        wire = wires[wire_index]
        for obstacle_index in range(len(obstacles)):
            obstacle = obstacles[obstacle_index]
            if _lines_intersect_values(
                wire[0], wire[1], wire[2], wire[3],
                obstacle[0], obstacle[1], obstacle[2], obstacle[3],
            ):
                return True
    return False


@njit(cache=True, nogil=True)
def point_hits_any_obstacle(point_x: int, point_y: int, obstacles: np.ndarray) -> bool:
    for obstacle_index in range(len(obstacles)):
        x1 = obstacles[obstacle_index, 0]
        y1 = obstacles[obstacle_index, 1]
        x2 = obstacles[obstacle_index, 2]
        y2 = obstacles[obstacle_index, 3]
        if x1 == x2:
            if point_x == x1 and min(y1, y2) <= point_y <= max(y1, y2):
                return True
        elif y1 == y2 and point_y == y1 and min(x1, x2) <= point_x <= max(x1, x2):
            return True
    return False


@njit(cache=True, nogil=True, parallel=True)
def candidate_point_validity_parallel(
    x_coordinates: np.ndarray,
    y_coordinates: np.ndarray,
    obstacles: np.ndarray,
    terminals: np.ndarray,
) -> np.ndarray:
    point_count = len(x_coordinates) * len(y_coordinates)
    validity = np.ones(point_count, dtype=np.bool_)
    y_count = len(y_coordinates)
    for point_index in prange(point_count):
        x_position = x_coordinates[point_index // y_count]
        y_position = y_coordinates[point_index % y_count]
        is_terminal = False
        for terminal_index in range(len(terminals)):
            if terminals[terminal_index, 0] == x_position and terminals[terminal_index, 1] == y_position:
                is_terminal = True
                break
        if not is_terminal and point_hits_any_obstacle(x_position, y_position, obstacles):
            validity[point_index] = False
    return validity


@njit(cache=True, nogil=True)
def candidate_point_validity_serial(
    x_coordinates: np.ndarray,
    y_coordinates: np.ndarray,
    obstacles: np.ndarray,
    terminals: np.ndarray,
) -> np.ndarray:
    point_count = len(x_coordinates) * len(y_coordinates)
    validity = np.ones(point_count, dtype=np.bool_)
    y_count = len(y_coordinates)
    for point_index in range(point_count):
        x_position = x_coordinates[point_index // y_count]
        y_position = y_coordinates[point_index % y_count]
        is_terminal = False
        for terminal_index in range(len(terminals)):
            if terminals[terminal_index, 0] == x_position and terminals[terminal_index, 1] == y_position:
                is_terminal = True
                break
        if not is_terminal and point_hits_any_obstacle(x_position, y_position, obstacles):
            validity[point_index] = False
    return validity


@njit(cache=True, inline="always")
def _wires_share_point_values(first, second) -> bool:
    x1a, y1a, x2a, y2a = first
    x1b, y1b, x2b, y2b = second
    first_vertical = x1a == x2a
    second_vertical = x1b == x2b
    if first_vertical and second_vertical:
        return x1a == x1b and _ranges_overlap(y1a, y2a, y1b, y2b)
    if not first_vertical and not second_vertical:
        return y1a == y1b and _ranges_overlap(x1a, x2a, x1b, x2b)
    if first_vertical:
        vertical_x, vertical_y1, vertical_y2 = x1a, y1a, y2a
        horizontal_x1, horizontal_x2, horizontal_y = x1b, x2b, y1b
    else:
        vertical_x, vertical_y1, vertical_y2 = x1b, y1b, y2b
        horizontal_x1, horizontal_x2, horizontal_y = x1a, x2a, y1a
    if not (
        min(horizontal_x1, horizontal_x2) <= vertical_x <= max(horizontal_x1, horizontal_x2)
        and min(vertical_y1, vertical_y2) <= horizontal_y <= max(vertical_y1, vertical_y2)
    ):
        return False
    intersection_x, intersection_y = vertical_x, horizontal_y
    return (
        (intersection_x == x1a and intersection_y == y1a)
        or (intersection_x == x2a and intersection_y == y2a)
        or (intersection_x == x1b and intersection_y == y1b)
        or (intersection_x == x2b and intersection_y == y2b)
    )


@njit(cache=True, nogil=True)
def wires_connected(wires: np.ndarray) -> bool:
    wire_count = len(wires)
    if wire_count <= 1:
        return True
    parent = np.arange(wire_count)
    for first_index in range(wire_count):
        for second_index in range(first_index + 1, wire_count):
            if not _wires_share_point_values(wires[first_index], wires[second_index]):
                continue
            first_root = first_index
            while parent[first_root] != first_root:
                parent[first_root] = parent[parent[first_root]]
                first_root = parent[first_root]
            second_root = second_index
            while parent[second_root] != second_root:
                parent[second_root] = parent[parent[second_root]]
                second_root = parent[second_root]
            if first_root != second_root:
                parent[second_root] = first_root
    root = 0
    while parent[root] != root:
        root = parent[root]
    for wire_index in range(1, wire_count):
        current_root = wire_index
        while parent[current_root] != current_root:
            current_root = parent[current_root]
        if current_root != root:
            return False
    return True


@njit(cache=True, nogil=True)
def endpoint_group_labels(wires: np.ndarray) -> np.ndarray:
    wire_count = len(wires)
    parent = np.arange(wire_count)
    for first_index in range(wire_count):
        first = wires[first_index]
        for second_index in range(first_index + 1, wire_count):
            second = wires[second_index]
            shares_endpoint = (
                (first[0] == second[0] and first[1] == second[1])
                or (first[0] == second[2] and first[1] == second[3])
                or (first[2] == second[0] and first[3] == second[1])
                or (first[2] == second[2] and first[3] == second[3])
            )
            if not shares_endpoint:
                continue
            first_root = first_index
            while parent[first_root] != first_root:
                parent[first_root] = parent[parent[first_root]]
                first_root = parent[first_root]
            second_root = second_index
            while parent[second_root] != second_root:
                parent[second_root] = parent[parent[second_root]]
                second_root = parent[second_root]
            if first_root != second_root:
                parent[second_root] = first_root
    labels = np.empty(wire_count, dtype=np.int64)
    for wire_index in range(wire_count):
        root = wire_index
        while parent[root] != root:
            parent[root] = parent[parent[root]]
            root = parent[root]
        labels[wire_index] = root
    return labels


@njit(cache=True, nogil=True, parallel=True)
def fill_rgb_buffer_parallel(buffer: np.ndarray, color: np.ndarray) -> None:
    for pixel_index in prange(len(buffer) // 3):
        pixel_offset = pixel_index * 3
        buffer[pixel_offset] = color[0]
        buffer[pixel_offset + 1] = color[1]
        buffer[pixel_offset + 2] = color[2]


@njit(cache=True, nogil=True)
def shortest_orientation_path(
    coordinates: np.ndarray,
    offsets: np.ndarray,
    neighbors: np.ndarray,
    edge_lengths: np.ndarray,
    start_index: int,
    end_index: int,
) -> np.ndarray:
    node_count = len(coordinates)
    state_count = node_count * 3
    infinity = np.iinfo(np.int64).max
    best_segments = np.full(state_count, infinity, dtype=np.int64)
    best_lengths = np.full(state_count, infinity, dtype=np.int64)
    previous_states = np.full(state_count, -1, dtype=np.int64)
    start_state = start_index * 3
    best_segments[start_state] = 0
    best_lengths[start_state] = 0
    queue = [(0, 0, coordinates[start_index, 0], coordinates[start_index, 1], 0, start_index)]
    final_state = -1
    while queue:
        segment_count, route_length, _point_x, _point_y, orientation, node_index = heapq.heappop(queue)
        current_state = node_index * 3 + orientation
        if best_segments[current_state] != segment_count or best_lengths[current_state] != route_length:
            continue
        if node_index == end_index:
            final_state = current_state
            break
        for edge_index in range(offsets[node_index], offsets[node_index + 1]):
            neighbor_index = neighbors[edge_index]
            if coordinates[node_index, 0] == coordinates[neighbor_index, 0]:
                edge_orientation = 2
            else:
                edge_orientation = 1
            next_segment_count = segment_count
            if orientation != edge_orientation:
                next_segment_count += 1
            next_route_length = route_length + edge_lengths[edge_index]
            next_state = neighbor_index * 3 + edge_orientation
            if (
                next_segment_count > best_segments[next_state]
                or (
                    next_segment_count == best_segments[next_state]
                    and next_route_length >= best_lengths[next_state]
                )
            ):
                continue
            best_segments[next_state] = next_segment_count
            best_lengths[next_state] = next_route_length
            previous_states[next_state] = current_state
            heapq.heappush(
                queue,
                (
                    next_segment_count,
                    next_route_length,
                    coordinates[neighbor_index, 0],
                    coordinates[neighbor_index, 1],
                    edge_orientation,
                    neighbor_index,
                ),
            )
    if final_state < 0:
        return np.empty(0, dtype=np.int64)
    reverse_path = np.empty(state_count, dtype=np.int64)
    path_length = 0
    current_state = final_state
    while current_state >= 0:
        reverse_path[path_length] = current_state // 3
        path_length += 1
        current_state = previous_states[current_state]
    result = np.empty(path_length, dtype=np.int64)
    for path_index in range(path_length):
        result[path_index] = reverse_path[path_length - path_index - 1]
    return result
