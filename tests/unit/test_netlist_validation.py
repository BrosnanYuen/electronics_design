"""Unit tests for full LTspice netlist validation."""  # Describe the unit-test module purpose.

from __future__ import annotations  # Keep annotation handling consistent across the project.

from pathlib import Path  # Use pathlib for clear fixture-path handling.
import unittest  # Use the standard library test framework.

from electronics_design import is_valid_ltspice_netlist_file  # Import the public whole-file validator.

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]  # Resolve the project root from the current test file.
_VALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "netlist_validation" / "valid"  # Point to valid full-validation fixtures.
_INVALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "netlist_validation" / "invalid"  # Point to invalid full-validation fixtures.
_EXPECTED_INVALID_RESULTS = {  # Map each invalid fixture file to the exact public error tuple it should produce.
    "invalid_01.net": (False, "Line format/spacing is invalid! Line 2"),  # Expect the merged resistor token fixture to fail on line two.
    "invalid_02.net": (False, "Line format/spacing is invalid! Line 4"),  # Expect the merged directive fixture to fail on line four.
    "invalid_03.net": (False, "Line format/spacing is invalid! Line 1"),  # Expect the orphan continuation fixture to fail on line one.
    "invalid_04.net": (False, "Line format/spacing is invalid! Line 1"),  # Expect the invalid leading keyword fixture to fail on line one.
    "invalid_05.net": (False, "Footer information is invalid! Line 4"),  # Expect the missing-backanno fixture to fail on line four.
    "invalid_06.net": (False, "Footer information is invalid! Line 5"),  # Expect the missing-analysis fixture to fail on line five.
    "invalid_07.net": (False, "Footer information is invalid! Line 6"),  # Expect the misplaced footer directive fixture to fail on line six.
    "invalid_08.net": (False, "Node is not connected correctly! Line 2"),  # Expect the isolated resistor node fixture to fail on line two.
    "invalid_09.net": (False, "Node is not connected correctly! Line 5"),  # Expect the isolated transistor emitter node fixture to fail on line five.
    "invalid_10.net": (False, "Node is not connected correctly! Line 2"),  # Expect the isolated capacitor branch fixture to fail on line two.
}  # Finish the invalid-fixture result map.


class TestNetlistValidation(unittest.TestCase):  # Group whole-file validation test cases together.
    def test_valid_validation_fixtures(self) -> None:  # Verify that all valid whole-file fixtures pass the public wrapper validator.
        for fixture_path in sorted(_VALID_DIRECTORY.glob("*.net")):  # Walk every valid whole-file fixture file.
            result = is_valid_ltspice_netlist_file(str(fixture_path))  # Execute the whole-file validator on the fixture path.
            self.assertTrue(result[0], msg=f"{fixture_path.name} should be valid but returned: {result[1]}")  # Assert that the fixture validates successfully.
            self.assertEqual(result[1], "", msg=f"{fixture_path.name} should not produce an error message.")  # Assert that successful validation returns an empty message.

    def test_invalid_validation_fixtures(self) -> None:  # Verify that all invalid whole-file fixtures fail with the expected public error tuple.
        for fixture_path in sorted(_INVALID_DIRECTORY.glob("*.net")):  # Walk every invalid whole-file fixture file.
            expected_result = _EXPECTED_INVALID_RESULTS[fixture_path.name]  # Look up the exact public error tuple expected for the fixture.
            result = is_valid_ltspice_netlist_file(str(fixture_path))  # Execute the whole-file validator on the fixture path.
            self.assertEqual(result, expected_result, msg=f"{fixture_path.name} returned an unexpected validation result.")  # Assert that the wrapper returns the expected propagated error tuple.
