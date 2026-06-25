"""Unit tests for LTspice ASC spacing validation."""  # Describe the unit-test module purpose.

from __future__ import annotations  # Keep annotation handling consistent across the project.

from pathlib import Path  # Use pathlib for clear fixture-path handling.
import unittest  # Use the standard library test framework.

from electronics_design import is_valid_ltspice_asc_spacing  # Import the public ASC spacing validator.

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]  # Resolve the project root from the current test file.
_VALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "asc_spacing" / "valid"  # Point to valid ASC spacing fixtures.
_INVALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "asc_spacing" / "invalid"  # Point to invalid ASC spacing fixtures.


class TestAscSpacing(unittest.TestCase):  # Group ASC spacing-validator test cases together.
    def test_valid_spacing_fixtures(self) -> None:  # Verify that all valid ASC spacing fixtures pass the public validator.
        for fixture_path in sorted(_VALID_DIRECTORY.glob("*.asc")):  # Walk every valid ASC spacing fixture file.
            result = is_valid_ltspice_asc_spacing(str(fixture_path))  # Execute the public validator on the fixture path.
            self.assertTrue(result[0], msg=f"{fixture_path.name} should be valid but returned: {result[1]}")  # Assert that the fixture validates successfully.
            self.assertEqual(result[1], "", msg=f"{fixture_path.name} should not produce an error message.")  # Assert that successful validation returns an empty message.

    def test_invalid_spacing_fixtures(self) -> None:  # Verify that all invalid ASC spacing fixtures fail the public validator.
        for fixture_path in sorted(_INVALID_DIRECTORY.glob("*.asc")):  # Walk every invalid ASC spacing fixture file.
            expected_line = fixture_path.stem.rsplit("_", 1)[-1]  # Extract the expected line number from the fixture name.
            result = is_valid_ltspice_asc_spacing(str(fixture_path))  # Execute the public validator on the fixture path.
            self.assertFalse(result[0], msg=f"{fixture_path.name} should be invalid.")  # Assert that the fixture fails validation.
            self.assertIn("Line format/spacing is invalid!", result[1], msg=f"{fixture_path.name} should report a spacing error.")  # Assert that the correct error prefix is returned.
            self.assertIn(f"Line {expected_line}", result[1], msg=f"{fixture_path.name} should report the expected line number.")  # Assert that the reported failing line matches the fixture name.
