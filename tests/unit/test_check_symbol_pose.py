"""Unit tests for buffered LTspice symbol-pose collision detection."""

from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np

from electronics_design import ltspice_check_symbol_pose

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]
_COLLIDING_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "symbol_colliding"
_NOT_COLLIDING_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "symbol_not_colliding"
_CONVERT_SETTINGS = {
    "ltspice_windows_path": "C:\\users\\brosnan\\AppData\\Local\\LTspice\\",
    "ltspice_wine_path": "~/.wine/drive_c/users/brosnan/AppData/Local/LTspice/",
    "custom_search_paths": ["./valid_asy/"],
    "minimum_dist": 32,
    "grid_size": 16,
    "voltage_must_have_dc": False,
}
_EXPECTED_COLLISIONS = {
    "case_01.json": np.array([[0, 1]], dtype=int),
    "case_02.json": np.array([[0, 1]], dtype=int),
    "case_03.json": np.array([[0, 1]], dtype=int),
    "case_04.json": np.array([[0, 1], [1, 2]], dtype=int),
    "case_05.json": np.array([[0, 1], [0, 2], [1, 2]], dtype=int),
    "case_06.json": np.array([[0, 1]], dtype=int),
    "case_07.json": np.array([[0, 1]], dtype=int),
    "case_08.json": np.array([[0, 1]], dtype=int),
    "case_09.json": np.array([[0, 1]], dtype=int),
    "case_10.json": np.array([[0, 1], [2, 3]], dtype=int),
}


class TestLtspiceCheckSymbolPose(unittest.TestCase):
    def test_all_colliding_symbol_fixtures_return_expected_symbol_pairs(self) -> None:
        fixture_paths = sorted(_COLLIDING_DIRECTORY.glob("*.json"))
        self.assertEqual(len(fixture_paths), 10, msg="The colliding symbol-pose tests require exactly 10 fixtures.")
        for fixture_path in fixture_paths:
            with self.subTest(fixture=fixture_path.name):
                result = ltspice_check_symbol_pose(str(fixture_path), _CONVERT_SETTINGS)
                self.assertTrue(result[0], msg=f"{fixture_path.name} should report symbol collisions.")
                self.assertIsNotNone(result[1], msg=f"{fixture_path.name} should return collision index pairs.")
                np.testing.assert_array_equal(
                    result[1],
                    _EXPECTED_COLLISIONS[fixture_path.name],
                    err_msg=f"{fixture_path.name} returned unexpected colliding symbol index pairs.",
                )

    def test_all_non_colliding_symbol_fixtures_return_false_none(self) -> None:
        fixture_paths = sorted(_NOT_COLLIDING_DIRECTORY.glob("*.json"))
        self.assertEqual(len(fixture_paths), 10, msg="The non-colliding symbol-pose tests require exactly 10 fixtures.")
        for fixture_path in fixture_paths:
            with self.subTest(fixture=fixture_path.name):
                self.assertEqual(
                    ltspice_check_symbol_pose(str(fixture_path), _CONVERT_SETTINGS),
                    (False, None),
                    msg=f"{fixture_path.name} should not report symbol collisions.",
                )

    def test_zero_buffer_does_not_turn_nearby_symbols_into_collision(self) -> None:
        fixture_path = _COLLIDING_DIRECTORY / "case_02.json"
        result = ltspice_check_symbol_pose(
            str(fixture_path),
            {
                "ltspice_windows_path": "C:\\users\\brosnan\\AppData\\Local\\LTspice\\",
                "ltspice_wine_path": "~/.wine/drive_c/users/brosnan/AppData/Local/LTspice/",
                "custom_search_paths": ["./valid_asy/"],
                "minimum_dist": 0,
                "grid_size": 16,
                "voltage_must_have_dc": False,
            },
        )
        self.assertEqual(result, (False, None))
