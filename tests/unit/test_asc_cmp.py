"""Unit tests for LTspice ASC structural comparison."""

from __future__ import annotations

from pathlib import Path
import unittest

from electronics_design import ltspice_asc_structure_cmp

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]
_VALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "asc_cmp" / "valid"
_INVALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "asc_cmp" / "invalid"
_REFERENCE_ASC_DIRECTORY = _ROOT_DIRECTORY / "valid_convert" / "asc"
_CONVERT_SETTINGS = {
    "ltspice_windows_path": "C:\\users\\brosnan\\AppData\\Local\\LTspice\\",
    "ltspice_wine_path": "~/.wine/drive_c/users/brosnan/AppData/Local/LTspice/",
    "grid_size": 16,
    "voltage_must_have_dc": False,
}
_EXPECTED_INVALID_LINES = {
    1: 14,
    2: 11,
    3: 18,
    4: 23,
    5: 12,
    6: 15,
    7: 14,
    8: 20,
    9: 11,
    10: 18,
}


class TestAscComparison(unittest.TestCase):
    def test_structure_comparison_accepts_drawing_without_analysis_directive(self) -> None:
        drawing_path = (
            _REFERENCE_ASC_DIRECTORY
            / "Adjustable-duty-cycle-555-square-wave-oscillator.asc"
        )
        self.assertEqual(
            ltspice_asc_structure_cmp(
                str(drawing_path),
                str(drawing_path),
                _CONVERT_SETTINGS,
            ),
            (True, "", 0),
        )

    def test_valid_comparison_pairs(self) -> None:
        for case_number in range(1, 11):
            first_path = _VALID_DIRECTORY / f"valid_case_{case_number:02d}_a.asc"
            second_path = _VALID_DIRECTORY / f"valid_case_{case_number:02d}_b.asc"
            result = ltspice_asc_structure_cmp(str(first_path), str(second_path), _CONVERT_SETTINGS)
            self.assertEqual(result, (True, "", 0), msg=f"valid comparison case {case_number:02d} should be structurally equivalent.")

    def test_invalid_comparison_pairs(self) -> None:
        for case_number in range(1, 11):
            first_path = _INVALID_DIRECTORY / f"invalid_case_{case_number:02d}_a.asc"
            second_path = _INVALID_DIRECTORY / f"invalid_case_{case_number:02d}_b.asc"
            result = ltspice_asc_structure_cmp(str(first_path), str(second_path), _CONVERT_SETTINGS)
            self.assertFalse(result[0], msg=f"invalid comparison case {case_number:02d} should not be structurally equivalent.")
            self.assertEqual(result[1], "ASC structures are different!", msg=f"invalid comparison case {case_number:02d} should report the stable mismatch message.")
            self.assertEqual(result[2], _EXPECTED_INVALID_LINES[case_number], msg=f"invalid comparison case {case_number:02d} should report the expected line number.")
