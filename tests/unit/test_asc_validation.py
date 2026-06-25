"""Unit tests for full LTspice ASC file validation."""  # Describe the unit-test module purpose.

from __future__ import annotations  # Keep annotation handling consistent across the project.

from pathlib import Path  # Use pathlib for clear fixture-path handling.
import unittest  # Use the standard library test framework.

from electronics_design import is_valid_ltspice_asc_file  # Import the public ASC whole-file validator.

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]  # Resolve the project root from the current test file.
_VALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "asc_validation" / "valid"  # Point to valid ASC whole-file fixtures.
_INVALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "asc_validation" / "invalid"  # Point to invalid ASC whole-file fixtures.
_EXPECTED_INVALID_RESULTS = {  # Map each invalid fixture file to the exact public error tuple it should produce.
    "invalid_01.asc": (False, "Header information is invalid! Line 1"),  # Expect the missing Version header fixture to fail on line one.
    "invalid_02.asc": (False, "Header information is invalid! Line 2"),  # Expect the malformed SHEET header fixture to fail on line two.
    "invalid_03.asc": (False, "Line format/spacing is invalid! Line 3"),  # Expect the malformed WIRE record fixture to fail on line three.
    "invalid_04.asc": (False, "Line format/spacing is invalid! Line 4"),  # Expect the malformed TEXT record fixture to fail on line four.
    "invalid_05.asc": (False, "Footer information is invalid! Line 4"),  # Expect the no-analysis fixture to fail on the final nonblank line.
    "invalid_06.asc": (False, "Footer information is invalid! Line 4"),  # Expect the merged directive fixture to fail on the directive line.
}  # Finish the invalid-fixture result map.


class TestAscValidation(unittest.TestCase):  # Group ASC whole-file validation test cases together.
    def test_valid_validation_fixtures(self) -> None:  # Verify that all valid ASC whole-file fixtures pass the public wrapper validator.
        for fixture_path in sorted(_VALID_DIRECTORY.glob("*.asc")):  # Walk every valid ASC whole-file fixture file.
            result = is_valid_ltspice_asc_file(str(fixture_path))  # Execute the whole-file validator on the fixture path.
            self.assertTrue(result[0], msg=f"{fixture_path.name} should be valid but returned: {result[1]}")  # Assert that the fixture validates successfully.
            self.assertEqual(result[1], "", msg=f"{fixture_path.name} should not produce an error message.")  # Assert that successful validation returns an empty message.

    def test_invalid_validation_fixtures(self) -> None:  # Verify that all invalid ASC whole-file fixtures fail with the expected public error tuple.
        for fixture_path in sorted(_INVALID_DIRECTORY.glob("*.asc")):  # Walk every invalid ASC whole-file fixture file.
            expected_result = _EXPECTED_INVALID_RESULTS[fixture_path.name]  # Look up the exact public error tuple expected for the fixture.
            result = is_valid_ltspice_asc_file(str(fixture_path))  # Execute the whole-file validator on the fixture path.
            self.assertEqual(result, expected_result, msg=f"{fixture_path.name} returned an unexpected validation result.")  # Assert that the wrapper returns the expected propagated error tuple.
