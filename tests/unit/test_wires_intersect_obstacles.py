"""Unit tests for are_wires_intersecting_obstacles in pathtracing."""

from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np

from electronics_design.pathtracing import are_wires_intersecting_obstacles

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]
_VALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "wires_intersect_obstacles" / "valid"
_INVALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "wires_intersect_obstacles" / "invalid"


def _parse_intersect_file(filepath: Path):
    wires = []
    obstacles = []
    for line in filepath.read_text(encoding="utf-8").splitlines():
        stripped_line = line.strip()
        if stripped_line == "":
            continue
        parts = stripped_line.split()
        if len(parts) != 5:
            continue
        line_values = [int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])]
        if parts[0].upper() == "WIRE":
            wires.append(line_values)
        elif parts[0].upper() == "OBSTACLE":
            obstacles.append(line_values)
    return np.array(wires, dtype=int), np.array(obstacles, dtype=int)


class TestAreWiresIntersectingObstacles(unittest.TestCase):
    def test_all_valid_cases_return_true(self) -> None:
        for fixture_path in sorted(_VALID_DIRECTORY.glob("*.txt")):
            wires, obstacles = _parse_intersect_file(fixture_path)
            self.assertTrue(len(wires) > 0, msg=f"{fixture_path.name} should contain valid WIRE entries.")
            result = are_wires_intersecting_obstacles(wires, obstacles)
            self.assertTrue(result, msg=f"{fixture_path.name} should return True.")

    def test_all_invalid_cases_return_false(self) -> None:
        for fixture_path in sorted(_INVALID_DIRECTORY.glob("*.txt")):
            wires, obstacles = _parse_intersect_file(fixture_path)
            self.assertTrue(len(wires) > 0, msg=f"{fixture_path.name} should contain valid WIRE entries.")
            result = are_wires_intersecting_obstacles(wires, obstacles)
            self.assertFalse(result, msg=f"{fixture_path.name} should return False.")

    def test_empty_wires_returns_false(self) -> None:
        result = are_wires_intersecting_obstacles(
            np.empty((0, 4), dtype=int),
            np.array([[32, 32, 96, 32]]),
        )
        self.assertFalse(result)

    def test_empty_obstacles_returns_false(self) -> None:
        result = are_wires_intersecting_obstacles(
            np.array([[32, 32, 96, 32]]),
            np.empty((0, 4), dtype=int),
        )
        self.assertFalse(result)

    def test_both_empty_returns_false(self) -> None:
        result = are_wires_intersecting_obstacles(
            np.empty((0, 4), dtype=int),
            np.empty((0, 4), dtype=int),
        )
        self.assertFalse(result)

    def test_vertical_wire_crosses_horizontal_obstacle_returns_true(self) -> None:
        wires = np.array([[128, 64, 128, 320]])
        obstacles = np.array([[64, 192, 256, 192]])
        self.assertTrue(are_wires_intersecting_obstacles(wires, obstacles))

    def test_horizontal_wire_crosses_vertical_obstacle_returns_true(self) -> None:
        wires = np.array([[64, 192, 256, 192]])
        obstacles = np.array([[128, 64, 128, 320]])
        self.assertTrue(are_wires_intersecting_obstacles(wires, obstacles))

    def test_adjacent_parallel_lines_no_overlap_returns_false(self) -> None:
        wires = np.array([[64, 128, 256, 128]])
        obstacles = np.array([[320, 128, 512, 128]])
        self.assertFalse(are_wires_intersecting_obstacles(wires, obstacles))

    def test_adjacent_perpendicular_no_overlap_returns_false(self) -> None:
        wires = np.array([[128, 64, 128, 256]])
        obstacles = np.array([[256, 256, 256, 448]])
        self.assertFalse(are_wires_intersecting_obstacles(wires, obstacles))

    def test_invalid_wires_shape_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            are_wires_intersecting_obstacles(
                np.array([[0, 0, 10]]),
                np.array([[32, 32, 96, 32]]),
            )

    def test_invalid_obstacles_shape_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            are_wires_intersecting_obstacles(
                np.array([[32, 32, 96, 32]]),
                np.array([[0, 0, 10]]),
            )

    def test_1d_wires_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            are_wires_intersecting_obstacles(
                np.array([0, 0, 10, 0]),
                np.array([[32, 32, 96, 32]]),
            )

    def test_1d_obstacles_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            are_wires_intersecting_obstacles(
                np.array([[32, 32, 96, 32]]),
                np.array([0, 0, 10, 0]),
            )
