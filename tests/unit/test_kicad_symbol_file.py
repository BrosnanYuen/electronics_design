"""Unit tests for KiCad symbol library file validation."""  # Describe the unit-test module purpose.

from __future__ import annotations  # Keep annotation handling consistent across the project.

from pathlib import Path  # Use pathlib for clear fixture-path handling.
import unittest  # Use the standard library test framework.

from electronics_design import is_valid_kicad_symbol_file  # Import the public KiCad symbol library whole-file validator.

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]  # Resolve the project root from the current test file.
_VALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "kicad_symbol_file" / "valid"  # Point to valid symbol library fixtures.
_INVALID_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "kicad_symbol_file" / "invalid"  # Point to invalid symbol library fixtures.
_EXPECTED_INVALID_RESULTS = {  # Map each invalid fixture file to the exact public error tuple it should produce.
    "invalid_01_line_1.kicad_sym": (False, "Header information is invalid! Line 1"),  # Expect the wrong-root fixture to fail on line one.
    "invalid_02_line_2.kicad_sym": (False, "Header information is invalid! Line 2"),  # Expect the malformed version fixture to fail on line two.
    "invalid_03_line_1.kicad_sym": (False, "Header information is invalid! Line 1"),  # Expect the missing generator fixture to fail on the root line.
    "invalid_04_line_1.kicad_sym": (False, "Header information is invalid! Line 1"),  # Expect the duplicated version fixture to fail on the root line.
    "invalid_05_line_5.kicad_sym": (False, "Line format/spacing is invalid! Line 5"),  # Expect the unclosed root fixture to fail as a spacing problem.
    "invalid_06_line_5.kicad_sym": (False, "Line format/spacing is invalid! Line 5"),  # Expect the trailing junk fixture to fail as a spacing problem.
    "invalid_07_line_4.kicad_sym": (False, "Symbol information is invalid! Line 4"),  # Expect the empty library fixture to fail on the final nonblank line.
    "invalid_08_line_4.kicad_sym": (False, "Symbol information is invalid! Line 4"),  # Expect the missing in_bom fixture to fail on the symbol line.
    "invalid_09_line_4.kicad_sym": (False, "Symbol information is invalid! Line 4"),  # Expect the bad on_board value fixture to fail on the symbol line.
    "invalid_10_line_4.kicad_sym": (False, "Symbol information is invalid! Line 4"),  # Expect the missing Reference property fixture to fail on the symbol line.
    "invalid_11_line_12.kicad_sym": (False, "Symbol information is invalid! Line 12"),  # Expect the unknown pin type fixture to fail on the pin line.
    "invalid_12_line_12.kicad_sym": (False, "Symbol information is invalid! Line 12"),  # Expect the missing pin number fixture to fail on the pin line.
    "invalid_13_line_12.kicad_sym": (False, "Symbol information is invalid! Line 12"),  # Expect the malformed pin position fixture to fail on the pin line.
    "invalid_14_line_13.kicad_sym": (False, "Footer information is invalid! Line 13"),  # Expect the trailing comment fixture to fail on the final nonblank line.
}  # Finish the invalid-fixture result map.


class TestKicadSymbolFile(unittest.TestCase):  # Group KiCad symbol library whole-file validation test cases together.
    def test_valid_symbol_fixtures(self) -> None:  # Verify that all valid symbol library fixtures pass the public validator.
        for fixture_path in sorted(_VALID_DIRECTORY.glob("*.kicad_sym")):  # Walk every valid symbol library fixture file.
            result = is_valid_kicad_symbol_file(str(fixture_path))  # Execute the whole-file validator on the fixture path.
            self.assertTrue(result[0], msg=f"{fixture_path.name} should be valid but returned: {result[1]}")  # Assert that the fixture validates successfully.
            self.assertEqual(result[1], "", msg=f"{fixture_path.name} should not produce an error message.")  # Assert that successful validation returns an empty message.

    def test_invalid_symbol_fixtures(self) -> None:  # Verify that all invalid symbol library fixtures fail with the expected public error tuple.
        for fixture_path in sorted(_INVALID_DIRECTORY.glob("*.kicad_sym")):  # Walk every invalid symbol library fixture file.
            expected_result = _EXPECTED_INVALID_RESULTS[fixture_path.name]  # Look up the exact public error tuple expected for the fixture.
            result = is_valid_kicad_symbol_file(str(fixture_path))  # Execute the whole-file validator on the fixture path.
            self.assertEqual(result, expected_result, msg=f"{fixture_path.name} returned an unexpected validation result.")  # Assert that the validator returns the expected error tuple.


if __name__ == "__main__":  # Allow running the module directly for debugging.
    unittest.main()  # Execute the unit tests when invoked as a script.
