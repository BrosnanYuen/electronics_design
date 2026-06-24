"""Unit tests for LTspice netlist footer validation."""  # Describe the unit-test module purpose.

from __future__ import annotations  # Keep annotation handling consistent across the project.

from pathlib import Path  # Use pathlib for clear fixture-path handling.
import unittest  # Use the standard library test framework.

from electronics_design import is_valid_ltspice_netlist_footer  # Import the public footer validator.

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]  # Resolve the project root from the current test file.
_VALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "netlist_footer" / "valid"  # Point to valid footer fixtures.
_INVALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "netlist_footer" / "invalid"  # Point to invalid footer fixtures.


class TestNetlistFooter(unittest.TestCase):  # Group footer-validator test cases together.
    def test_valid_footer_fixtures(self) -> None:  # Verify that all valid footer fixtures pass the public validator.
        for fixture_path in sorted(_VALID_DIRECTORY.glob("*.net")):  # Walk every valid footer fixture file.
            result = is_valid_ltspice_netlist_footer(str(fixture_path))  # Execute the public validator on the fixture path.
            self.assertTrue(result[0], msg=f"{fixture_path.name} should be valid but returned: {result[1]}")  # Assert that the fixture validates successfully.
            self.assertEqual(result[1], "", msg=f"{fixture_path.name} should not produce an error message.")  # Assert that successful validation returns an empty message.

    def test_invalid_footer_fixtures(self) -> None:  # Verify that all invalid footer fixtures fail the public validator.
        for fixture_path in sorted(_INVALID_DIRECTORY.glob("*.net")):  # Walk every invalid footer fixture file.
            expected_line = fixture_path.stem.rsplit("_", 1)[-1]  # Extract the expected line number from the fixture name.
            result = is_valid_ltspice_netlist_footer(str(fixture_path))  # Execute the public validator on the fixture path.
            self.assertFalse(result[0], msg=f"{fixture_path.name} should be invalid.")  # Assert that the fixture fails validation.
            self.assertIn("Footer information is invalid!", result[1], msg=f"{fixture_path.name} should report a footer error.")  # Assert that the correct error prefix is returned.
            self.assertIn(f"Line {expected_line}", result[1], msg=f"{fixture_path.name} should report the expected line number.")  # Assert that the reported failing line matches the fixture name.
