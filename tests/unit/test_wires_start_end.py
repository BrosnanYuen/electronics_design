"""Unit tests for get_wires_startpos_endpos in pathtracing."""

from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np

from electronics_design.pathtracing import get_wires_startpos_endpos

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]
_FIXTURE_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "wire_start_end"

_EXPECTED_ENDPOINTS = {
    "case_01.txt": (np.array([160, 192]), np.array([432, 384])),
    "case_02.txt": (np.array([224, 160]), np.array([416, 352])),
    "case_03.txt": (np.array([32, 64]), np.array([224, 96])),
    "case_04.txt": (np.array([64, 64]), np.array([192, 64])),
    "case_05.txt": (np.array([128, 128]), np.array([384, 128])),
    "case_06.txt": (np.array([16, 32]), np.array([272, 80])),
    "case_07.txt": (np.array([128, 128]), np.array([320, 192])),
    "case_08.txt": (np.array([48, 48]), np.array([384, 48])),
    "case_09.txt": (np.array([64, 288]), np.array([448, 192])),
    "case_10.txt": (np.array([80, 400]), np.array([464, 80])),
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


class TestGetWiresStartposEndpos(unittest.TestCase):
    def test_all_fixture_cases(self) -> None:
        for fixture_name, (expected_start, expected_end) in sorted(_EXPECTED_ENDPOINTS.items()):
            fixture_path = _FIXTURE_DIRECTORY / fixture_name
            wires = _parse_fixture(fixture_path)
            self.assertTrue(len(wires) > 0, msg=f"{fixture_name} should contain valid WIRE entries.")
            startpos, endpos = get_wires_startpos_endpos(wires)
            np.testing.assert_array_equal(startpos, expected_start, err_msg=f"{fixture_name} unexpected startpos.")
            np.testing.assert_array_equal(endpos, expected_end, err_msg=f"{fixture_name} unexpected endpos.")

    def test_single_horizontal_wire(self) -> None:
        wires = np.array([[0, 0, 64, 0]])
        startpos, endpos = get_wires_startpos_endpos(wires)
        np.testing.assert_array_equal(startpos, np.array([0, 0]))
        np.testing.assert_array_equal(endpos, np.array([64, 0]))

    def test_single_vertical_wire(self) -> None:
        wires = np.array([[32, 0, 32, 80]])
        startpos, endpos = get_wires_startpos_endpos(wires)
        np.testing.assert_array_equal(startpos, np.array([32, 0]))
        np.testing.assert_array_equal(endpos, np.array([32, 80]))

    def test_l_shape_three_wires(self) -> None:
        wires = np.array([[0, 32, 64, 32], [64, 32, 64, 96], [64, 96, 128, 96]])
        startpos, endpos = get_wires_startpos_endpos(wires)
        np.testing.assert_array_equal(startpos, np.array([0, 32]))
        np.testing.assert_array_equal(endpos, np.array([128, 96]))

    def test_reversed_wire_order_yields_same_endpoints(self) -> None:
        wires = np.array([[256, 384, 432, 384], [160, 192, 256, 192], [256, 192, 256, 384]])
        startpos, endpos = get_wires_startpos_endpos(wires)
        np.testing.assert_array_equal(startpos, np.array([160, 192]))
        np.testing.assert_array_equal(endpos, np.array([432, 384]))

    def test_collinear_touching_wires(self) -> None:
        wires = np.array([[0, 0, 32, 0], [32, 0, 64, 0], [64, 0, 96, 0]])
        startpos, endpos = get_wires_startpos_endpos(wires)
        np.testing.assert_array_equal(startpos, np.array([0, 0]))
        np.testing.assert_array_equal(endpos, np.array([96, 0]))

    def test_invalid_shape_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            get_wires_startpos_endpos(np.array([[0, 0, 10]]))

    def test_1d_array_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            get_wires_startpos_endpos(np.array([0, 0, 10, 0]))

    def test_open_chain_raises_value_error(self) -> None:
        wires = np.array([[0, 0, 32, 0], [64, 0, 96, 0]])
        with self.assertRaises(ValueError):
            get_wires_startpos_endpos(wires)

    def test_branch_with_four_endpoints_raises_value_error(self) -> None:
        wires = np.array([[32, 0, 32, 32], [32, 32, 0, 32], [32, 32, 64, 32], [32, 32, 32, 64]])
        with self.assertRaises(ValueError):
            get_wires_startpos_endpos(wires)

    def test_empty_array_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            get_wires_startpos_endpos(np.empty((0, 4), dtype=int))
