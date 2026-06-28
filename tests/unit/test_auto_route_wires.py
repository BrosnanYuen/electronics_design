"""Unit tests for the grid-based auto_route_wires API."""

from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np

from electronics_design import auto_route_wires
from electronics_design.pathtracing import are_wires_connected
from electronics_design.pathtracing import are_wires_horizontal_or_vertical
from electronics_design.pathtracing import are_wires_intersecting_obstacles_fast

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]
_VALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "auto_route_wires" / "valid"
_INVALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "auto_route_wires" / "invalid"
_GRID_X = 16
_GRID_Y = 16


def _parse_route_fixture(filepath: Path) -> tuple[tuple[int, int], tuple[int, int], np.ndarray, np.ndarray]:
    flags: list[tuple[int, int]] = []
    obstacles: list[list[int]] = []
    wires: list[list[int]] = []
    for raw_line in filepath.read_text(encoding="utf-8").splitlines():
        stripped_line = raw_line.strip()
        if stripped_line == "":
            continue
        tokens = stripped_line.split()
        keyword = tokens[0].upper()
        if keyword == "FLAG" and len(tokens) == 3:
            flags.append((int(tokens[1]), int(tokens[2])))
            continue
        if keyword == "OBSTACLE" and len(tokens) == 5:
            obstacles.append([int(tokens[1]), int(tokens[2]), int(tokens[3]), int(tokens[4])])
            continue
        if keyword == "WIRE" and len(tokens) == 5:
            wires.append([int(tokens[1]), int(tokens[2]), int(tokens[3]), int(tokens[4])])
    if len(flags) != 2:
        raise ValueError(f"{filepath.name} must contain exactly two FLAG records.")
    obstacle_array = np.asarray(obstacles, dtype=int) if obstacles else np.empty((0, 4), dtype=int)
    wire_array = np.asarray(wires, dtype=int) if wires else np.empty((0, 4), dtype=int)
    return flags[0], flags[1], obstacle_array, wire_array


def _points_are_on_grid(start_point: tuple[int, int], end_point: tuple[int, int]) -> bool:
    return (
        start_point[0] % _GRID_X == 0
        and start_point[1] % _GRID_Y == 0
        and end_point[0] % _GRID_X == 0
        and end_point[1] % _GRID_Y == 0
    )


def _obstacles_are_on_grid(obstacles: np.ndarray) -> bool:
    if len(obstacles) == 0:
        return True
    return bool(
        np.all(obstacles[:, 0] % _GRID_X == 0)
        and np.all(obstacles[:, 2] % _GRID_X == 0)
        and np.all(obstacles[:, 1] % _GRID_Y == 0)
        and np.all(obstacles[:, 3] % _GRID_Y == 0)
    )


def _obstacles_are_axis_aligned(obstacles: np.ndarray) -> bool:
    if len(obstacles) == 0:
        return True
    return bool(np.all((obstacles[:, 0] == obstacles[:, 2]) | (obstacles[:, 1] == obstacles[:, 3])))


def _path_matches_flags(wires: np.ndarray, start_point: tuple[int, int], end_point: tuple[int, int]) -> bool:
    if len(wires) == 0:
        return False
    return tuple(wires[0, 0:2]) == start_point and tuple(wires[-1, 2:4]) == end_point


class TestAutoRouteWires(unittest.TestCase):
    def test_valid_route_fixtures(self) -> None:
        for fixture_path in sorted(_VALID_DIRECTORY.glob("*.txt")):
            with self.subTest(fixture=fixture_path.name):
                start_point, end_point, obstacles, expected_wires = _parse_route_fixture(fixture_path)
                result = auto_route_wires(
                    start_point[0],
                    start_point[1],
                    end_point[0],
                    end_point[1],
                    obstacles,
                    _GRID_X,
                    _GRID_Y,
                )
                np.testing.assert_array_equal(
                    result,
                    expected_wires,
                    err_msg=f"{fixture_path.name} produced an unexpected route.",
                )
                self.assertTrue(len(result) > 0, msg=f"{fixture_path.name} should produce at least one routed wire.")
                self.assertTrue(are_wires_horizontal_or_vertical(result), msg=f"{fixture_path.name} should be axis-aligned.")
                self.assertTrue(are_wires_connected(result), msg=f"{fixture_path.name} should be connected.")
                self.assertFalse(
                    are_wires_intersecting_obstacles_fast(result, obstacles),
                    msg=f"{fixture_path.name} should avoid obstacle intersections.",
                )
                self.assertTrue(_path_matches_flags(result, start_point, end_point), msg=f"{fixture_path.name} should start and end at the FLAG points.")
                self.assertTrue(_points_are_on_grid(start_point, end_point), msg=f"{fixture_path.name} uses off-grid FLAG coordinates.")
                self.assertTrue(_obstacles_are_on_grid(obstacles), msg=f"{fixture_path.name} uses off-grid obstacles.")
                self.assertTrue(np.all(result[:, 0] % _GRID_X == 0) and np.all(result[:, 2] % _GRID_X == 0), msg=f"{fixture_path.name} has off-grid X wire coordinates.")
                self.assertTrue(np.all(result[:, 1] % _GRID_Y == 0) and np.all(result[:, 3] % _GRID_Y == 0), msg=f"{fixture_path.name} has off-grid Y wire coordinates.")

    def test_invalid_route_fixtures_raise_value_error(self) -> None:
        for fixture_path in sorted(_INVALID_DIRECTORY.glob("*.txt")):
            with self.subTest(fixture=fixture_path.name):
                start_point, end_point, obstacles, reference_wires = _parse_route_fixture(fixture_path)
                reference_is_obviously_invalid = (
                    not _points_are_on_grid(start_point, end_point)
                    or not _obstacles_are_on_grid(obstacles)
                    or not _obstacles_are_axis_aligned(obstacles)
                    or not are_wires_horizontal_or_vertical(reference_wires)
                    or not are_wires_connected(reference_wires)
                    or are_wires_intersecting_obstacles_fast(reference_wires, obstacles)
                    or not _path_matches_flags(reference_wires, start_point, end_point)
                )
                self.assertTrue(
                    reference_is_obviously_invalid or len(obstacles) >= 4,
                    msg=f"{fixture_path.name} should document an invalid or unroutable case.",
                )
                with self.assertRaises(ValueError, msg=f"{fixture_path.name} should be rejected by auto_route_wires."):
                    auto_route_wires(
                        start_point[0],
                        start_point[1],
                        end_point[0],
                        end_point[1],
                        obstacles,
                        _GRID_X,
                        _GRID_Y,
                    )
