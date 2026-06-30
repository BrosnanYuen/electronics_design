"""Unit tests for get_wires_endpos in pathtracing."""

from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np

from electronics_design.pathtracing import get_wires_endpos

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]
_FIXTURE_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "wire_start_end"

_EXPECTED_RESULTS = {
    "case_01.txt": np.array([[160, 192], [432, 384]], dtype=int),
    "case_02.txt": np.array([[224, 160], [416, 352]], dtype=int),
    "case_03.txt": np.array([[240, 304], [400, 560], [768, 176], [816, 480]], dtype=int),
    "case_04.txt": np.array([[128, 128], [384, 128], [512, 256]], dtype=int),
    "case_05.txt": np.array([[0, 64], [384, 64]], dtype=int),
    "case_06.txt": np.array([[320, 240], [512, 384]], dtype=int),
    "case_07.txt": np.array([[128, 256], [160, 160], [256, 96], [256, 384], [384, 256]], dtype=int),
    "case_08.txt": np.array([[192, 256], [320, 128], [320, 384], [448, 256]], dtype=int),
    "case_09.txt": np.array([[64, 128], [576, 512]], dtype=int),
    "case_10.txt": np.array([[96, 256], [384, 384], [480, 96]], dtype=int),
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
        for fixture_name, expected_result in sorted(_EXPECTED_RESULTS.items()):
            fixture_path = _FIXTURE_DIRECTORY / fixture_name
            wires = _parse_fixture(fixture_path)
            self.assertTrue(len(wires) > 0, msg=f"{fixture_name} should contain valid WIRE entries.")
            endpos = get_wires_endpos(wires)
            np.testing.assert_array_equal(endpos, expected_result, err_msg=f"{fixture_name} unexpected end positions.")

    def test_single_horizontal_wire(self) -> None:
        wires = np.array([[0, 0, 64, 0]])
        endpos = get_wires_endpos(wires)
        np.testing.assert_array_equal(endpos, np.array([[0, 0], [64, 0]]))

    def test_single_vertical_wire(self) -> None:
        wires = np.array([[32, 0, 32, 80]])
        endpos = get_wires_endpos(wires)
        np.testing.assert_array_equal(endpos, np.array([[32, 0], [32, 80]]))

    def test_l_shape_three_wires(self) -> None:
        wires = np.array([[0, 32, 64, 32], [64, 32, 64, 96], [64, 96, 128, 96]])
        endpos = get_wires_endpos(wires)
        np.testing.assert_array_equal(endpos, np.array([[0, 32], [128, 96]]))

    def test_reversed_wire_order_yields_same_endpoints(self) -> None:
        wires = np.array([[256, 384, 432, 384], [160, 192, 256, 192], [256, 192, 256, 384]])
        endpos = get_wires_endpos(wires)
        np.testing.assert_array_equal(endpos, np.array([[160, 192], [432, 384]]))

    def test_collinear_touching_wires(self) -> None:
        wires = np.array([[0, 0, 32, 0], [32, 0, 64, 0], [64, 0, 96, 0]])
        endpos = get_wires_endpos(wires)
        np.testing.assert_array_equal(endpos, np.array([[0, 0], [96, 0]]))

    def test_collinear_overlapping_wires(self) -> None:
        wires = np.array([[0, 0, 32, 0], [16, 0, 48, 0]])
        endpos = get_wires_endpos(wires)
        np.testing.assert_array_equal(endpos, np.array([[0, 0], [48, 0]]))

    def test_collinear_contained_wire(self) -> None:
        wires = np.array([[0, 0, 48, 0], [16, 0, 32, 0]])
        endpos = get_wires_endpos(wires)
        np.testing.assert_array_equal(endpos, np.array([[0, 0], [48, 0]]))

    def test_t_junction_returns_three_endpoints(self) -> None:
        wires = np.array([[128, 128, 128, 256], [128, 256, 256, 256], [128, 256, 384, 128], [128, 256, 512, 256]])
        endpos = get_wires_endpos(wires)
        np.testing.assert_array_equal(endpos, np.array([[128, 128], [384, 128], [512, 256]]))

    def test_interior_branch_point_not_an_endpoint(self) -> None:
        wires = np.array([[96, 256, 288, 256], [288, 256, 288, 96], [288, 96, 480, 96], [288, 256, 384, 384]])
        endpos = get_wires_endpos(wires)
        np.testing.assert_array_equal(endpos, np.array([[96, 256], [384, 384], [480, 96]]))

    def test_branch_on_interior_with_four_endpoints(self) -> None:
        wires = np.array([
            [768, 176, 320, 176],
            [320, 176, 320, 400],
            [320, 400, 720, 400],
            [720, 400, 720, 560],
            [720, 560, 400, 560],
            [720, 480, 816, 480],
            [320, 304, 240, 304],
        ])
        endpos = get_wires_endpos(wires)
        np.testing.assert_array_equal(endpos, np.array([[240, 304], [400, 560], [768, 176], [816, 480]]))

    def test_invalid_shape_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            get_wires_endpos(np.array([[0, 0, 10]]))

    def test_1d_array_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            get_wires_endpos(np.array([0, 0, 10, 0]))

    def test_open_chain_raises_value_error(self) -> None:
        wires = np.array([[0, 0, 32, 0], [64, 0, 96, 0]])
        with self.assertRaises(ValueError):
            get_wires_endpos(wires)

    def test_empty_array_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            get_wires_endpos(np.empty((0, 4), dtype=int))
