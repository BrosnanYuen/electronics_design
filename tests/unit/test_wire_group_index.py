"""Unit tests for find_wire_group_index in pathtracing."""

from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np

from electronics_design.pathtracing import find_wire_group_index
from electronics_design.pathtracing import place_wires_into_groups

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]
_FIXTURE_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "wire_group_index"

_EXPECTED_RESULTS = {
    "case_01.txt": (np.array([160, 192]), 0),
    "case_02.txt": (np.array([448, 272]), 1),
    "case_03.txt": (np.array([704, 464]), 2),
    "case_04.txt": (np.array([240, 336]), 0),
    "case_05.txt": (np.array([76, 64]), -1),
    "case_06.txt": (np.array([576, 624]), 1),
    "case_07.txt": (np.array([704, 464]), 2),
    "case_08.txt": (np.array([128, 160]), 0),
    "case_09.txt": (np.array([256, 208]), 1),
    "case_10.txt": (np.array([256, 64]), -1),
    "case_11.txt": (np.array([64, 0]), 0),
    "case_12.txt": (np.array([384, 64]), 2),
    "case_13.txt": (np.array([384, 64]), 2),
    "case_14.txt": (np.array([200, 200]), -1),
    "case_15.txt": (np.array([192, 160]), 0),
}


def _parse_wire_fixture(filepath: Path) -> np.ndarray:
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


class TestFindWireGroupIndex(unittest.TestCase):
    def test_all_fixture_cases(self) -> None:
        for fixture_name, (point, expected_index) in sorted(_EXPECTED_RESULTS.items()):
            with self.subTest(fixture=fixture_name):
                fixture_path = _FIXTURE_DIRECTORY / fixture_name
                wires = _parse_wire_fixture(fixture_path)
                groups = place_wires_into_groups(wires)
                result = find_wire_group_index(point, groups)
                self.assertEqual(result, expected_index,
                                 msg=f"{fixture_name}: expected {expected_index}, got {result}")

    def test_point_on_endpoint_returns_correct_index(self) -> None:
        groups = [
            np.array([[0, 0, 64, 0], [64, 0, 64, 64]], dtype=int),
            np.array([[128, 0, 192, 0]], dtype=int),
        ]
        self.assertEqual(find_wire_group_index(np.array([0, 0]), groups), 0)
        self.assertEqual(find_wire_group_index(np.array([64, 0]), groups), 0)
        self.assertEqual(find_wire_group_index(np.array([128, 0]), groups), 1)

    def test_point_on_interior_returns_correct_index(self) -> None:
        groups = [
            np.array([[0, 0, 0, 64]], dtype=int),
            np.array([[64, 0, 64, 64]], dtype=int),
        ]
        self.assertEqual(find_wire_group_index(np.array([0, 32]), groups), 0)
        self.assertEqual(find_wire_group_index(np.array([64, 32]), groups), 1)

    def test_point_not_found_returns_negative_one(self) -> None:
        groups = [
            np.array([[0, 0, 64, 0]], dtype=int),
            np.array([[64, 64, 128, 64]], dtype=int),
        ]
        self.assertEqual(find_wire_group_index(np.array([32, 32]), groups), -1)
        self.assertEqual(find_wire_group_index(np.array([100, 100]), groups), -1)

    def test_empty_groups_list_returns_negative_one(self) -> None:
        result = find_wire_group_index(np.array([32, 32]), [])
        self.assertEqual(result, -1)

    def test_invalid_point_shape_raises_value_error(self) -> None:
        groups = [np.array([[0, 0, 64, 0]], dtype=int)]
        with self.assertRaises(ValueError):
            find_wire_group_index(np.array([0, 0, 10]), groups)

    def test_invalid_1d_point_shape_raises_value_error(self) -> None:
        groups = [np.array([[0, 0, 64, 0]], dtype=int)]
        with self.assertRaises(ValueError):
            find_wire_group_index(np.array([0]), groups)

    def test_invalid_group_shape_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            find_wire_group_index(np.array([0, 0]), [np.array([[0, 0, 10]], dtype=int)])
