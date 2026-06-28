"""Unit tests for are_wires_intersecting_obstacles_detailed in pathtracing."""

from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np

from electronics_design.pathtracing import are_wires_intersecting_obstacles_detailed

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]
_VALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "wires_intersect_obstacles_detailed" / "valid"
_INVALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "wires_intersect_obstacles_detailed" / "invalid"

_EXPECTED_INTERSECTIONS = {
    "valid_01.txt": np.array([[0, 0]], dtype=int),
    "valid_02.txt": np.array([[0, 0]], dtype=int),
    "valid_03.txt": np.array([[0, 0]], dtype=int),
    "valid_04.txt": np.array([[0, 0], [0, 1]], dtype=int),
    "valid_05.txt": np.array([[0, 0], [1, 0]], dtype=int),
    "valid_06.txt": np.array([[0, 0]], dtype=int),
    "valid_07.txt": np.array([[0, 0]], dtype=int),
    "valid_08.txt": np.array([[0, 0]], dtype=int),
    "valid_09.txt": np.array([[0, 0], [0, 1], [1, 0], [1, 1], [2, 0], [2, 1]], dtype=int),
    "valid_10.txt": np.array([[0, 0], [0, 2], [1, 1], [2, 0], [2, 2]], dtype=int),
}


def _parse_detailed_file(filepath: Path):
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
    wires_array = np.array(wires, dtype=int)
    obstacles_array = np.array(obstacles, dtype=int)
    if wires_array.ndim == 1:
        wires_array = wires_array.reshape(0, 4)
    if obstacles_array.ndim == 1:
        obstacles_array = obstacles_array.reshape(0, 4)
    return wires_array, obstacles_array


def _assert_detailed_result(test_case, result, expected_has_intersection, expected_intersections):
    test_case.assertEqual(result[0], expected_has_intersection)
    if expected_has_intersection:
        test_case.assertIsNotNone(result[1])
        np.testing.assert_array_equal(result[1], expected_intersections)
    else:
        test_case.assertIsNone(result[1])


class TestAreWiresIntersectingObstaclesDetailed(unittest.TestCase):
    def test_all_valid_cases_return_true_with_correct_indices(self) -> None:
        for fixture_path in sorted(_VALID_DIRECTORY.glob("*.txt")):
            with self.subTest(fixture=fixture_path.name):
                wires, obstacles = _parse_detailed_file(fixture_path)
                self.assertTrue(len(wires) > 0, msg=f"{fixture_path.name} should contain valid WIRE entries.")
                self.assertTrue(len(obstacles) > 0, msg=f"{fixture_path.name} should contain valid OBSTACLE entries.")
                result = are_wires_intersecting_obstacles_detailed(wires, obstacles)
                _assert_detailed_result(self, result, True, _EXPECTED_INTERSECTIONS[fixture_path.name])

    def test_all_invalid_cases_return_false_none(self) -> None:
        for fixture_path in sorted(_INVALID_DIRECTORY.glob("*.txt")):
            with self.subTest(fixture=fixture_path.name):
                wires, obstacles = _parse_detailed_file(fixture_path)
                result = are_wires_intersecting_obstacles_detailed(wires, obstacles)
                _assert_detailed_result(self, result, False, None)

    def test_vertical_wire_crosses_horizontal_obstacle(self) -> None:
        wires = np.array([[128, 64, 128, 320]])
        obstacles = np.array([[64, 192, 256, 192]])
        result = are_wires_intersecting_obstacles_detailed(wires, obstacles)
        _assert_detailed_result(self, result, True, np.array([[0, 0]], dtype=int))

    def test_horizontal_wire_crosses_vertical_obstacle(self) -> None:
        wires = np.array([[64, 192, 256, 192]])
        obstacles = np.array([[128, 64, 128, 320]])
        result = are_wires_intersecting_obstacles_detailed(wires, obstacles)
        _assert_detailed_result(self, result, True, np.array([[0, 0]], dtype=int))

    def test_adjacent_parallel_no_overlap_returns_false(self) -> None:
        wires = np.array([[64, 128, 256, 128]])
        obstacles = np.array([[320, 128, 512, 128]])
        result = are_wires_intersecting_obstacles_detailed(wires, obstacles)
        _assert_detailed_result(self, result, False, None)

    def test_adjacent_perpendicular_no_overlap_returns_false(self) -> None:
        wires = np.array([[128, 64, 128, 256]])
        obstacles = np.array([[256, 256, 256, 448]])
        result = are_wires_intersecting_obstacles_detailed(wires, obstacles)
        _assert_detailed_result(self, result, False, None)

    def test_empty_wires_returns_false(self) -> None:
        result = are_wires_intersecting_obstacles_detailed(
            np.empty((0, 4), dtype=int),
            np.array([[32, 32, 96, 32]]),
        )
        _assert_detailed_result(self, result, False, None)

    def test_empty_obstacles_returns_false(self) -> None:
        result = are_wires_intersecting_obstacles_detailed(
            np.array([[32, 32, 96, 32]]),
            np.empty((0, 4), dtype=int),
        )
        _assert_detailed_result(self, result, False, None)

    def test_both_empty_returns_false(self) -> None:
        result = are_wires_intersecting_obstacles_detailed(
            np.empty((0, 4), dtype=int),
            np.empty((0, 4), dtype=int),
        )
        _assert_detailed_result(self, result, False, None)

    def test_invalid_wires_shape_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            are_wires_intersecting_obstacles_detailed(
                np.array([[0, 0, 10]]),
                np.array([[32, 32, 96, 32]]),
            )

    def test_invalid_obstacles_shape_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            are_wires_intersecting_obstacles_detailed(
                np.array([[32, 32, 96, 32]]),
                np.array([[0, 0, 10]]),
            )

    def test_1d_wires_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            are_wires_intersecting_obstacles_detailed(
                np.array([0, 0, 10, 0]),
                np.array([[32, 32, 96, 32]]),
            )

    def test_1d_obstacles_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            are_wires_intersecting_obstacles_detailed(
                np.array([[32, 32, 96, 32]]),
                np.array([0, 0, 10, 0]),
            )
