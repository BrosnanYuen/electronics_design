"""Unit tests for LTspice ASY symbol bounding-rectangle extraction."""

from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np

from electronics_design import get_ltspice_asy_size
from electronics_design import is_valid_ltspice_asy

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]
_FIXTURE_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "asy_size"
_EXPECTED_BOUNDS = {
    "case_01.asy": np.array([[-16, -32], [48, 32]], dtype=int),
    "case_02.asy": np.array([[-40, -56], [32, 24]], dtype=int),
    "case_03.asy": np.array([[-10, -20], [30, 40]], dtype=int),
    "case_04.asy": np.array([[-16, -48], [16, -16]], dtype=int),
    "case_05.asy": np.array([[-32, -48], [32, 48]], dtype=int),
    "case_06.asy": np.array([[-32, -48], [32, 32]], dtype=int),
    "case_07.asy": np.array([[-48, -80], [48, 80]], dtype=int),
    "case_08.asy": np.array([[-5, -30], [40, 35]], dtype=int),
    "case_09.asy": np.array([[-20, -30], [20, 40]], dtype=int),
    "case_10.asy": np.array([[-24, -8], [48, 64]], dtype=int),
    "case_11.asy": np.array([[-64, -16], [32, 48]], dtype=int),
    "case_12.asy": np.array([[-48, -48], [60, 60]], dtype=int),
    "case_13.asy": np.array([[-100, 5], [-20, 45]], dtype=int),
    "case_14.asy": np.array([[-16, -80], [72, 32]], dtype=int),
    "case_15.asy": np.array([[-32, -48], [32, 64]], dtype=int),
    "case_16.asy": np.array([[-40, -20], [20, 20]], dtype=int),
    "case_17.asy": np.array([[-60, -50], [40, 50]], dtype=int),
    "case_18.asy": np.array([[-30, -30], [30, 30]], dtype=int),
    "case_19.asy": np.array([[-24, -24], [24, 24]], dtype=int),
    "case_20.asy": np.array([[-80, -40], [84, 40]], dtype=int),
}


class TestAsySize(unittest.TestCase):
    def test_all_size_fixtures_are_valid(self) -> None:
        fixture_paths = sorted(_FIXTURE_DIRECTORY.glob("*.asy"))
        self.assertEqual(len(fixture_paths), 20, msg="The ASY size tests require exactly 20 fixtures.")
        for fixture_path in fixture_paths:
            with self.subTest(fixture=fixture_path.name):
                result = is_valid_ltspice_asy(str(fixture_path))
                self.assertEqual(result, (True, ""), msg=f"{fixture_path.name} should be a valid LTspice ASY file.")

    def test_all_size_fixtures_return_expected_bounds(self) -> None:
        for fixture_name, expected_bounds in sorted(_EXPECTED_BOUNDS.items()):
            fixture_path = _FIXTURE_DIRECTORY / fixture_name
            with self.subTest(fixture=fixture_name):
                actual_bounds = get_ltspice_asy_size(str(fixture_path))
                np.testing.assert_array_equal(
                    actual_bounds,
                    expected_bounds,
                    err_msg=f"{fixture_name} returned an unexpected LTspice ASY bounding rectangle.",
                )
