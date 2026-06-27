"""Unit tests for LTspice netlist footer comparison."""  # Describe the unit-test module purpose.

from __future__ import annotations  # Keep annotation handling consistent across the project.

from pathlib import Path  # Use pathlib for clear fixture-path handling.
import unittest  # Use the standard library test framework.

from electronics_design import ltspice_netlist_footer_cmp  # Import the public footer comparison helper.

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]  # Resolve the project root from the current test file.
_VALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "netlist_footer_cmp" / "valid"  # Point to valid footer-comparison fixture pairs.
_INVALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "netlist_footer_cmp" / "invalid"  # Point to invalid footer-comparison fixture pairs.


class TestNetlistFooterComparison(unittest.TestCase):  # Group footer-comparison test cases together.
    def test_valid_footer_pairs(self) -> None:  # Verify that every valid footer-comparison pair is reported as equivalent.
        for case_number in range(1, 11):  # Walk every valid footer-comparison case number.
            first_path = _VALID_DIRECTORY / f"valid_case_{case_number:02d}_a.net"  # Resolve the first fixture file for the current valid case.
            second_path = _VALID_DIRECTORY / f"valid_case_{case_number:02d}_b.net"  # Resolve the second fixture file for the current valid case.
            result = ltspice_netlist_footer_cmp(str(first_path), str(second_path))  # Execute the footer comparison helper on the valid pair.
            self.assertTrue(result, msg=f"valid footer comparison case {case_number:02d} should have matching footers.")  # Assert that the valid pair compares as footer-equivalent.

    def test_invalid_footer_pairs(self) -> None:  # Verify that every invalid footer-comparison pair is reported as different.
        for case_number in range(1, 11):  # Walk every invalid footer-comparison case number.
            first_path = _INVALID_DIRECTORY / f"invalid_case_{case_number:02d}_a.net"  # Resolve the first fixture file for the current invalid case.
            second_path = _INVALID_DIRECTORY / f"invalid_case_{case_number:02d}_b.net"  # Resolve the second fixture file for the current invalid case.
            result = ltspice_netlist_footer_cmp(str(first_path), str(second_path))  # Execute the footer comparison helper on the invalid pair.
            self.assertFalse(result, msg=f"invalid footer comparison case {case_number:02d} should have different footers.")  # Assert that the invalid pair compares as footer-different.
