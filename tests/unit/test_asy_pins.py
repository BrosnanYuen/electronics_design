"""Unit tests for LTspice ASY pin extraction and rectangle edge generation."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np

from electronics_design import get_ltspice_asy_pins
from electronics_design import is_valid_ltspice_asy
from electronics_design import rectangle_points_to_lines

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]
_FIXTURE_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "asy_pins"
_EXPECTED_PINS = {
    "case_01.asy": [[16, 0, "A", 1], [16, 64, "B", 2]],
    "case_02.asy": [[-32, 80, "In+", 1], [-32, 48, "In-", 2], [0, 32, "V+", 3], [0, 96, "V-", 4], [32, 64, "OUT", 5]],
    "case_03.asy": [[-32, -8, "N", 1], [32, -8, "P", 2]],
    "case_04.asy": [[-32, 16, "BASE", 1], [32, 0, "COLLECTOR", 2], [0, 48, "EMITTER", 3]],
    "case_05.asy": [[-48, 0, "IN1", 1], [0, -48, "IN2", 2], [48, 0, "OUT1", 3], [0, 48, "OUT2", 4]],
    "case_06.asy": [[0, 0, "P1", 1]],
    "case_07.asy": [[-32, -16, "IN", 1], [32, -16, "OUT", 2], [0, 32, "EN", 3]],
    "case_08.asy": [[-64, 0, "LEFT", 1], [64, 0, "RIGHT", 2], [0, -48, "TOP", 3]],
    "case_09.asy": [[-96, -32, "N1", 1], [-32, -96, "N2", 2], [32, -32, "N3", 3]],
    "case_10.asy": [[-16, 64, "CTRL", 1], [16, 64, "SENSE", 2], [0, -16, "OUT", 3]],
    "case_11.asy": [[-48, 16, "VIN", 1], [0, -32, "VREF", 2], [48, 16, "VOUT", 3], [0, 64, "GND", 4]],
    "case_12.asy": [[-64, 0, "A1", 1], [-16, -48, "A2", 2], [16, 48, "A3", 3], [64, 0, "A4", 4]],
    "case_13.asy": [[-48, 32, "L+", 1], [-48, -32, "L-", 2], [48, 0, "R", 3]],
    "case_14.asy": [[-80, -16, "I1", 1], [-80, 16, "I2", 2], [80, -16, "O1", 3], [80, 16, "O2", 4]],
    "case_15.asy": [[0, -64, "TOP", 1], [-64, 0, "LEFT", 2], [64, 0, "RIGHT", 3], [0, 64, "BOTTOM", 4]],
    "case_16.asy": [[-32, 0, "NEG", 1], [32, 0, "POS", 2]],
    "case_17.asy": [[-96, 32, "CLK", 1], [-96, -32, "DATA", 2], [96, 0, "Q", 3], [0, 96, "RST", 4]],
    "case_18.asy": [[0, -64, "PWR", 1], [-64, 0, "IN_A", 2], [-64, 32, "IN_B", 3], [64, 16, "OUT", 4]],
    "case_19.asy": [[-48, -48, "A", 1], [48, -48, "B", 2], [-48, 48, "C", 3], [48, 48, "D", 4]],
    "case_20.asy": [[-80, 0, "IN", 1], [0, -80, "CFG", 2], [80, 0, "OUT", 3], [0, 80, "MON", 4], [48, 48, "AUX", 5]],
}


class TestAsyPins(unittest.TestCase):
    def test_all_pin_fixtures_are_valid(self) -> None:
        fixture_paths = sorted(_FIXTURE_DIRECTORY.glob("*.asy"))
        self.assertEqual(len(fixture_paths), 20, msg="The ASY pin tests require exactly 20 fixtures.")
        for fixture_path in fixture_paths:
            with self.subTest(fixture=fixture_path.name):
                result = is_valid_ltspice_asy(str(fixture_path))
                self.assertEqual(result, (True, ""), msg=f"{fixture_path.name} should be a valid LTspice ASY file.")

    def test_all_pin_fixtures_return_expected_pins(self) -> None:
        for fixture_name, expected_pins in sorted(_EXPECTED_PINS.items()):
            fixture_path = _FIXTURE_DIRECTORY / fixture_name
            with self.subTest(fixture=fixture_name):
                self.assertEqual(
                    get_ltspice_asy_pins(str(fixture_path)),
                    expected_pins,
                    msg=f"{fixture_name} returned unexpected LTspice ASY pins.",
                )

    def test_valid_symbol_without_pins_returns_empty_list(self) -> None:
        fixture_path = _ROOT_DIRECTORY / "test_files" / "asy_size" / "case_01.asy"
        self.assertEqual(get_ltspice_asy_pins(str(fixture_path)), [])

    def test_incomplete_pin_information_raises_value_error(self) -> None:
        invalid_asy_text = "\n".join(
            [
                "Version 4.1",
                "SymbolType CELL",
                "LINE Normal -16 0 16 0",
                "PIN -16 0 LEFT 8",
                "PINATTR PinName IN",
            ]
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            invalid_path = Path(temporary_directory) / "incomplete_pin.asy"
            invalid_path.write_text(invalid_asy_text, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "LTspice ASY pin information is incomplete! Line 4"):
                get_ltspice_asy_pins(str(invalid_path))


class TestRectanglePointsToLines(unittest.TestCase):
    def test_rectangle_points_to_lines_returns_expected_edges(self) -> None:
        points = np.array([[-16, -32], [48, 32]], dtype=int)
        expected_lines = np.array(
            [
                [-16, -32, 48, -32],
                [48, -32, 48, 32],
                [-16, -32, -16, 32],
                [-16, 32, 48, 32],
            ],
            dtype=int,
        )
        np.testing.assert_array_equal(rectangle_points_to_lines(points), expected_lines)

    def test_rectangle_points_to_lines_normalizes_corner_order(self) -> None:
        points = np.array([[48, 32], [-16, -32]], dtype=int)
        expected_lines = np.array(
            [
                [-16, -32, 48, -32],
                [48, -32, 48, 32],
                [-16, -32, -16, 32],
                [-16, 32, 48, 32],
            ],
            dtype=int,
        )
        np.testing.assert_array_equal(rectangle_points_to_lines(points), expected_lines)

    def test_rectangle_points_to_lines_rejects_invalid_shape(self) -> None:
        with self.assertRaisesRegex(ValueError, "shape"):
            rectangle_points_to_lines(np.array([[-16, -32, 48, 32]], dtype=int))

    def test_rectangle_points_to_lines_rejects_non_integer_coordinates(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be an integer"):
            rectangle_points_to_lines(np.array([[-16.0, -32.0], [48.0, 32.0]], dtype=float))
