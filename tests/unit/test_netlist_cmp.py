"""Unit tests for LTspice structural comparison."""  # Describe the unit-test module purpose.

from __future__ import annotations  # Keep annotation handling consistent across the project.

from pathlib import Path  # Use pathlib for clear fixture-path handling.
import unittest  # Use the standard library test framework.

from electronics_design import ltspice_netlist_structure_cmp  # Import the public structural comparison helper.

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]  # Resolve the project root from the current test file.
_VALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "netlist_cmp" / "valid"  # Point to valid structural-comparison fixture pairs.
_INVALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "netlist_cmp" / "invalid"  # Point to invalid structural-comparison fixture pairs.


class TestNetlistComparison(unittest.TestCase):  # Group structural-comparison test cases together.
    def test_valid_comparison_pairs(self) -> None:  # Verify that every valid comparison pair is reported as structurally equivalent.
        for case_number in range(1, 21):  # Walk every valid structural-comparison case number.
            first_path = _VALID_DIRECTORY / f"valid_case_{case_number:02d}_a.net"  # Resolve the first fixture file for the current valid case.
            second_path = _VALID_DIRECTORY / f"valid_case_{case_number:02d}_b.net"  # Resolve the second fixture file for the current valid case.
            result = ltspice_netlist_structure_cmp(str(first_path), str(second_path))  # Execute the structural comparison helper on the valid pair.
            self.assertTrue(result, msg=f"valid comparison case {case_number:02d} should be structurally equivalent.")  # Assert that the valid pair compares as structurally equal.

    def test_invalid_comparison_pairs(self) -> None:  # Verify that every invalid comparison pair is reported as structurally different.
        for case_number in range(1, 21):  # Walk every invalid structural-comparison case number.
            first_path = _INVALID_DIRECTORY / f"invalid_case_{case_number:02d}_a.net"  # Resolve the first fixture file for the current invalid case.
            second_path = _INVALID_DIRECTORY / f"invalid_case_{case_number:02d}_b.net"  # Resolve the second fixture file for the current invalid case.
            result = ltspice_netlist_structure_cmp(str(first_path), str(second_path))  # Execute the structural comparison helper on the invalid pair.
            self.assertFalse(result, msg=f"invalid comparison case {case_number:02d} should not be structurally equivalent.")  # Assert that the invalid pair compares as structurally different.
