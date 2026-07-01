"""Unit tests for place_wires_into_groups in pathtracing — groups of connected wires."""

from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np

from electronics_design.pathtracing import place_wires_into_groups

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]
_FIXTURE_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "wire_start_end"

_EXPECTED_GROUPS = {
    "case_01.txt": [
        np.array([[160, 192, 256, 192], [256, 192, 256, 384], [256, 384, 432, 384]], dtype=int),
    ],
    "case_02.txt": [
        np.array([[192, 336, 640, 336], [640, 336, 640, 544]], dtype=int),
        np.array([[448, 272, 832, 272]], dtype=int),
    ],
    "case_03.txt": [
        np.array(
            [[192, 336, 640, 336], [640, 336, 640, 544], [640, 544, 800, 544], [640, 336, 784, 336], [640, 336, 640, 224]],
            dtype=int,
        ),
        np.array([[448, 272, 832, 272]], dtype=int),
        np.array([[704, 464, 448, 464], [448, 464, 448, 544], [448, 464, 448, 416]], dtype=int),
    ],
    "case_04.txt": [
        np.array(
            [
                [352, 336, 352, 128], [464, 336, 464, 512], [352, 336, 240, 336],
                [352, 336, 464, 336], [464, 336, 640, 336], [640, 336, 640, 400],
                [640, 400, 752, 400],
            ],
            dtype=int,
        ),
        np.array([[64, 208, 576, 208], [576, 208, 576, 624], [576, 624, 208, 624]], dtype=int),
    ],
    "case_05.txt": [
        np.array([[320, 240, 512, 384]], dtype=int),
    ],
    "case_06.txt": [
        np.array([[128, 64, 128, 320]], dtype=int),
        np.array([[64, 192, 256, 192]], dtype=int),
    ],
    "case_07.txt": [
        np.array([[0, 0, 64, 0]], dtype=int),
        np.array([[32, 0, 32, 64], [32, 0, 96, 0]], dtype=int),
        np.array([[128, 64, 128, 192]], dtype=int),
        np.array([[64, 128, 192, 128]], dtype=int),
    ],
    "case_08.txt": [
        np.array(
            [[256, 256, 128, 256], [256, 256, 256, 128], [256, 256, 256, 384], [256, 256, 384, 256]],
            dtype=int,
        ),
    ],
    "case_09.txt": [
        np.array(
            [
                [64, 128, 192, 128], [192, 128, 192, 256], [192, 256, 320, 256],
                [320, 256, 320, 384], [320, 384, 448, 384],
            ],
            dtype=int,
        ),
    ],
    "case_10.txt": [
        np.array([[96, 256, 288, 256], [288, 256, 288, 96], [288, 96, 480, 96]], dtype=int),
        np.array([[384, 384, 576, 384], [576, 384, 576, 512]], dtype=int),
    ],
}


def _parse_fixture(filepath: Path) -> np.ndarray:
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


def _sort_groups(groups):
    sortable = [tuple(map(tuple, group)) for group in groups]
    sortable.sort(key=lambda g: (len(g), g[0] if len(g) else ()))
    return [np.array(group, dtype=int) for group in sortable]


class TestGetWiresEndpos(unittest.TestCase):
    def test_all_fixture_cases(self) -> None:
        for fixture_name in sorted(_EXPECTED_GROUPS.keys()):
            with self.subTest(fixture=fixture_name):
                fixture_path = _FIXTURE_DIRECTORY / fixture_name
                wires = _parse_fixture(fixture_path)
                self.assertTrue(len(wires) > 0, msg=f"{fixture_name} should contain valid WIRE entries.")
                groups = place_wires_into_groups(wires)
                self.assertEqual(len(groups), len(_EXPECTED_GROUPS[fixture_name]),
                                 msg=f"{fixture_name} should produce {len(_EXPECTED_GROUPS[fixture_name])} groups.")
                sorted_actual = _sort_groups(groups)
                sorted_expected = _sort_groups(_EXPECTED_GROUPS[fixture_name])
                for group_idx, (actual_group, expected_group) in enumerate(zip(sorted_actual, sorted_expected)):
                    np.testing.assert_array_equal(actual_group, expected_group,
                                                   err_msg=f"{fixture_name} group {group_idx} mismatch.")

    def test_two_collinear_wires_connected_by_endpoint(self) -> None:
        wires = np.array([[0, 0, 32, 0], [32, 0, 64, 0]])
        groups = place_wires_into_groups(wires)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]), 2)

    def test_two_collinear_wires_not_connected_without_shared_endpoint(self) -> None:
        wires = np.array([[0, 0, 16, 0], [32, 0, 64, 0]])
        groups = place_wires_into_groups(wires)
        self.assertEqual(len(groups), 2)

    def test_single_vertical_wire(self) -> None:
        wires = np.array([[32, 0, 32, 80]])
        groups = place_wires_into_groups(wires)
        self.assertEqual(len(groups), 1)
        np.testing.assert_array_equal(groups[0], wires)

    def test_invalid_shape_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            place_wires_into_groups(np.array([[0, 0, 10]]))

    def test_1d_array_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            place_wires_into_groups(np.array([0, 0, 10, 0]))

    def test_empty_array_returns_empty_list(self) -> None:
        groups = place_wires_into_groups(np.empty((0, 4), dtype=int))
        self.assertEqual(groups, [])

    def test_crossing_wires_not_connected(self) -> None:
        wires = np.array([[5, 0, 5, 10], [0, 5, 10, 5]])
        groups = place_wires_into_groups(wires)
        self.assertEqual(len(groups), 2)
