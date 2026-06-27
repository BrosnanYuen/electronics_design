"""Unit tests for are_wires_connected in pathtracing."""

from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np

from electronics_design.pathtracing import are_wires_connected

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]
_VALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "wires_connected" / "valid"
_INVALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "wires_connected" / "invalid"


def _parse_wire_file(filepath: Path) -> np.ndarray:
    wires = []
    for line in filepath.read_text(encoding="utf-8").splitlines():
        stripped_line = line.strip()
        if stripped_line == "":
            continue
        parts = stripped_line.split()
        if parts[0].upper() != "WIRE" or len(parts) != 5:
            continue
        wires.append([int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])])
    return np.array(wires, dtype=int)


class TestAreWiresConnected(unittest.TestCase):
    def test_all_valid_cases_return_true(self) -> None:
        for fixture_path in sorted(_VALID_DIRECTORY.glob("*.txt")):
            wires = _parse_wire_file(fixture_path)
            self.assertTrue(len(wires) > 0, msg=f"{fixture_path.name} should contain valid WIRE entries.")
            result = are_wires_connected(wires)
            self.assertTrue(result, msg=f"{fixture_path.name} should be connected.")

    def test_all_invalid_cases_return_false(self) -> None:
        for fixture_path in sorted(_INVALID_DIRECTORY.glob("*.txt")):
            wires = _parse_wire_file(fixture_path)
            self.assertTrue(len(wires) > 0, msg=f"{fixture_path.name} should contain valid WIRE entries.")
            result = are_wires_connected(wires)
            self.assertFalse(result, msg=f"{fixture_path.name} should not be connected.")

    def test_single_wire_is_connected(self) -> None:
        result = are_wires_connected(np.array([[0, 0, 10, 0]]))
        self.assertTrue(result)

    def test_empty_array_returns_true(self) -> None:
        result = are_wires_connected(np.empty((0, 4), dtype=int))
        self.assertTrue(result)

    def test_two_overlapping_collinear_wires_are_connected(self) -> None:
        wires = np.array([[0, 0, 10, 0], [5, 0, 15, 0]])
        result = are_wires_connected(wires)
        self.assertTrue(result)

    def test_vertical_horizontal_crossing_non_endpoint_not_connected(self) -> None:
        wires = np.array([[5, 0, 5, 10], [0, 5, 10, 5]])
        result = are_wires_connected(wires)
        self.assertFalse(result)

    def test_two_vertical_wires_same_x_overlapping_are_connected(self) -> None:
        wires = np.array([[10, 0, 10, 20], [10, 15, 10, 30]])
        result = are_wires_connected(wires)
        self.assertTrue(result)

    def test_two_parallel_offset_wires_not_connected(self) -> None:
        wires = np.array([[0, 0, 10, 0], [0, 20, 10, 20]])
        result = are_wires_connected(wires)
        self.assertFalse(result)

    def test_invalid_shape_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            are_wires_connected(np.array([[0, 0, 10]]))

    def test_1d_array_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            are_wires_connected(np.array([0, 0, 10, 0]))
