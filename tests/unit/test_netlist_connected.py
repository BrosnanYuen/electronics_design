"""Unit tests for LTspice connectivity validation."""  # Describe the unit-test module purpose.

from __future__ import annotations  # Keep annotation handling consistent across the project.

from pathlib import Path  # Use pathlib for clear fixture-path handling.
import unittest  # Use the standard library test framework.

from electronics_design import is_ltspice_netlist_structure_connected  # Import the public connectivity validator.

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]  # Resolve the project root from the current test file.
_VALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "netlist_connected" / "valid"  # Point to valid connectivity fixtures.
_INVALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "netlist_connected" / "invalid"  # Point to invalid connectivity fixtures.


class TestNetlistConnected(unittest.TestCase):  # Group connectivity-validator test cases together.
    def test_valid_connectivity_fixtures(self) -> None:  # Verify that all valid connectivity fixtures pass the public validator.
        for fixture_path in sorted(_VALID_DIRECTORY.glob("*.net")):  # Walk every valid connectivity fixture file.
            result = is_ltspice_netlist_structure_connected(str(fixture_path))  # Execute the public validator on the fixture path.
            self.assertTrue(result[0], msg=f"{fixture_path.name} should be valid but returned: {result[1]}")  # Assert that the fixture validates successfully.
            self.assertEqual(result[1], "", msg=f"{fixture_path.name} should not produce an error message.")  # Assert that successful validation returns an empty message.

    def test_invalid_connectivity_fixtures(self) -> None:  # Verify that all invalid connectivity fixtures fail the public validator.
        for fixture_path in sorted(_INVALID_DIRECTORY.glob("*.net")):  # Walk every invalid connectivity fixture file.
            expected_line = fixture_path.stem.rsplit("_", 1)[-1]  # Extract the expected line number from the fixture name.
            result = is_ltspice_netlist_structure_connected(str(fixture_path))  # Execute the public validator on the fixture path.
            self.assertFalse(result[0], msg=f"{fixture_path.name} should be invalid.")  # Assert that the fixture fails validation.
            self.assertIn("Node is not connected correctly!", result[1], msg=f"{fixture_path.name} should report a connectivity error.")  # Assert that the correct error prefix is returned.
            self.assertIn(f"Line {expected_line}", result[1], msg=f"{fixture_path.name} should report the expected line number.")  # Assert that the reported failing line matches the fixture name.
