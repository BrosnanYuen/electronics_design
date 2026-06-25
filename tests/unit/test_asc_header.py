"""Unit tests for LTspice ASC header validation."""  # Describe the unit-test module purpose.

from __future__ import annotations  # Keep annotation handling consistent across the project.

from pathlib import Path  # Use pathlib for clear fixture-path handling.
import unittest  # Use the standard library test framework.

from electronics_design import is_valid_ltspice_asc_header  # Import the public ASC header validator.

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]  # Resolve the project root from the current test file.
_VALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "asc_header" / "valid"  # Point to valid ASC header fixtures.
_INVALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "asc_header" / "invalid"  # Point to invalid ASC header fixtures.


class TestAscHeader(unittest.TestCase):  # Group ASC header-validator test cases together.
    def test_valid_header_fixtures(self) -> None:  # Verify that all valid ASC header fixtures pass the public validator.
        for fixture_path in sorted(_VALID_DIRECTORY.glob("*.asc")):  # Walk every valid ASC header fixture file.
            result = is_valid_ltspice_asc_header(str(fixture_path))  # Execute the public validator on the fixture path.
            self.assertTrue(result[0], msg=f"{fixture_path.name} should be valid but returned: {result[1]}")  # Assert that the fixture validates successfully.
            self.assertEqual(result[1], "", msg=f"{fixture_path.name} should not produce an error message.")  # Assert that successful validation returns an empty message.

    def test_invalid_header_fixtures(self) -> None:  # Verify that all invalid ASC header fixtures fail the public validator.
        for fixture_path in sorted(_INVALID_DIRECTORY.glob("*.asc")):  # Walk every invalid ASC header fixture file.
            expected_line = fixture_path.stem.rsplit("_", 1)[-1]  # Extract the expected line number from the fixture name.
            result = is_valid_ltspice_asc_header(str(fixture_path))  # Execute the public validator on the fixture path.
            self.assertFalse(result[0], msg=f"{fixture_path.name} should be invalid.")  # Assert that the fixture fails validation.
            self.assertIn("Header information is invalid!", result[1], msg=f"{fixture_path.name} should report a header error.")  # Assert that the correct error prefix is returned.
            self.assertIn(f"Line {expected_line}", result[1], msg=f"{fixture_path.name} should report the expected line number.")  # Assert that the reported failing line matches the fixture name.
