"""Unit tests for are_wires_horizontal_or_vertical in pathtracing."""

from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np

from electronics_design.pathtracing import are_wires_horizontal_or_vertical

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]
_VALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "wires_horizontal_vertical" / "valid"
_INVALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "wires_horizontal_vertical" / "invalid"


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


class TestAreWiresHorizontalOrVertical(unittest.TestCase):
    def test_all_valid_cases_return_true(self) -> None:
        for fixture_path in sorted(_VALID_DIRECTORY.glob("*.txt")):
            wires = _parse_wire_file(fixture_path)
            self.assertTrue(len(wires) > 0, msg=f"{fixture_path.name} should contain valid WIRE entries.")
            result = are_wires_horizontal_or_vertical(wires)
            self.assertTrue(result, msg=f"{fixture_path.name} should return True.")

    def test_all_invalid_cases_return_false(self) -> None:
        for fixture_path in sorted(_INVALID_DIRECTORY.glob("*.txt")):
            wires = _parse_wire_file(fixture_path)
            self.assertTrue(len(wires) > 0, msg=f"{fixture_path.name} should contain valid WIRE entries.")
            result = are_wires_horizontal_or_vertical(wires)
            self.assertFalse(result, msg=f"{fixture_path.name} should return False.")

    def test_single_horizontal_wire_returns_true(self) -> None:
        result = are_wires_horizontal_or_vertical(np.array([[0, 0, 100, 0]]))
        self.assertTrue(result)

    def test_single_vertical_wire_returns_true(self) -> None:
        result = are_wires_horizontal_or_vertical(np.array([[50, 0, 50, 100]]))
        self.assertTrue(result)

    def test_single_diagonal_wire_returns_false(self) -> None:
        result = are_wires_horizontal_or_vertical(np.array([[0, 0, 100, 100]]))
        self.assertFalse(result)

    def test_empty_array_returns_true(self) -> None:
        result = are_wires_horizontal_or_vertical(np.empty((0, 4), dtype=int))
        self.assertTrue(result)

    def test_mixed_horizontal_and_vertical_returns_true(self) -> None:
        wires = np.array([[0, 0, 10, 0], [10, 0, 10, 10], [10, 10, 0, 10]])
        result = are_wires_horizontal_or_vertical(wires)
        self.assertTrue(result)

    def test_one_diagonal_among_axis_aligned_returns_false(self) -> None:
        wires = np.array([[0, 0, 10, 0], [10, 0, 10, 10], [10, 10, 0, 20]])
        result = are_wires_horizontal_or_vertical(wires)
        self.assertFalse(result)

    def test_invalid_shape_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            are_wires_horizontal_or_vertical(np.array([[0, 0, 10]]))

    def test_1d_array_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            are_wires_horizontal_or_vertical(np.array([0, 0, 10, 0]))
