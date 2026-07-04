"""Unit tests for get_wire_pos — extract start and end points from wire arrays."""

from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np

from electronics_design import get_wire_pos

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]
_FIXTURE_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "get_wire_position"


class TestGetWirePos(unittest.TestCase):
    def test_all_fixture_cases(self) -> None:
        for case_number in range(1, 11):
            with self.subTest(case=case_number):
                wires_path = _FIXTURE_DIRECTORY / f"case_{case_number:02d}_wires.npy"
                expected_path = _FIXTURE_DIRECTORY / f"case_{case_number:02d}_expected.npy"
                wires = np.load(str(wires_path)).astype(int)
                expected = np.load(str(expected_path)).astype(int)
                result = get_wire_pos(wires)
                np.testing.assert_array_equal(
                    result,
                    expected,
                    err_msg=f"case {case_number:02d} returned unexpected wire positions.",
                )

    def test_example_from_spec(self) -> None:
        wires = np.array([
            [64, 144, 64, 64],
            [64, 144, -64, 144],
            [208, 144, 64, 144],
            [368, 144, 208, 144],
            [208, 256, 208, 144],
        ])
        expected = np.array([
            [64, 144], [64, 64],
            [64, 144], [-64, 144],
            [208, 144], [64, 144],
            [368, 144], [208, 144],
            [208, 256], [208, 144],
        ])
        np.testing.assert_array_equal(get_wire_pos(wires), expected)

    def test_single_wire(self) -> None:
        wires = np.array([[0, 0, 10, 20]])
        expected = np.array([[0, 0], [10, 20]])
        np.testing.assert_array_equal(get_wire_pos(wires), expected)

    def test_empty_array(self) -> None:
        result = get_wire_pos(np.empty((0, 4), dtype=int))
        self.assertEqual(len(result), 0)
        self.assertEqual(result.shape, (0, 2))

    def test_invalid_shape_raises_value_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be a 2D array with 4 columns"):
            get_wire_pos(np.array([[0, 0, 10]]))
        with self.assertRaisesRegex(ValueError, "must be a 2D array with 4 columns"):
            get_wire_pos(np.array([0, 0, 10, 0]))

    def test_result_dtype_is_int(self) -> None:
        wires = np.array([[0, 0, 10, 20]])
        result = get_wire_pos(wires)
        self.assertEqual(result.dtype, np.dtype(int))

    def test_three_wires(self) -> None:
        wires = np.array([
            [100, 200, 300, 400],
            [500, 600, 700, 800],
            [900, 1000, 1100, 1200],
        ])
        expected = np.array([
            [100, 200], [300, 400],
            [500, 600], [700, 800],
            [900, 1000], [1100, 1200],
        ])
        np.testing.assert_array_equal(get_wire_pos(wires), expected)
